/*
 * snd_macos.c -- Core Audio output for Quake's software mixer.
 */

#include <AudioToolbox/AudioToolbox.h>
#include <AudioUnit/AudioUnit.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "quakedef.h"

#define DMA_SAMPLE_COUNT 32768

extern int desired_speed;

static AudioUnit outputUnit;
static unsigned char *dmaBuffer;
static uint32_t playCursor;
static int audioRunning;

static void CoreAudioError(const char *operation, OSStatus status)
{
	Con_Printf("Core Audio: %s failed (%d)\n", operation, (int)status);
}

static void ClearAudioOutput(AudioBufferList *output)
{
	UInt32 i;

	for (i = 0; i < output->mNumberBuffers; ++i)
		memset(output->mBuffers[i].mData, 0,
			output->mBuffers[i].mDataByteSize);
}

static OSStatus CoreAudioRender(void *reference,
	AudioUnitRenderActionFlags *actionFlags,
	const AudioTimeStamp *timeStamp, UInt32 busNumber,
	UInt32 frameCount, AudioBufferList *output)
{
	AudioBuffer *buffer;
	uint32_t cursor;
	uint32_t samples;
	uint32_t copied;
	uint32_t chunk;
	uint32_t available;
	unsigned char *destination;
	UInt32 i;

	(void)reference;
	(void)actionFlags;
	(void)timeStamp;
	(void)busNumber;

	if (!__atomic_load_n(&audioRunning, __ATOMIC_ACQUIRE) ||
		!dmaBuffer || output->mNumberBuffers == 0)
	{
		ClearAudioOutput(output);
		return noErr;
	}

	/* Lock-free DMA consumer: always copy and always advance playCursor.
	 * The mixer writes ahead of this cursor (_snd_mixahead). */
	buffer = &output->mBuffers[0];
	destination = buffer->mData;
	samples = frameCount * 2;
	available = buffer->mDataByteSize / sizeof(short);
	if (samples > available)
		samples = available;

	cursor = __atomic_load_n(&playCursor, __ATOMIC_ACQUIRE);
	copied = 0;
	while (copied < samples)
	{
		chunk = DMA_SAMPLE_COUNT - cursor;
		if (chunk > samples - copied)
			chunk = samples - copied;
		memcpy(destination + copied * sizeof(short),
			dmaBuffer + cursor * sizeof(short),
			chunk * sizeof(short));
		copied += chunk;
		cursor = (cursor + chunk) & (DMA_SAMPLE_COUNT - 1);
	}

	if (copied * sizeof(short) < buffer->mDataByteSize)
		memset(destination + copied * sizeof(short), 0,
			buffer->mDataByteSize - copied * sizeof(short));
	for (i = 1; i < output->mNumberBuffers; ++i)
		memset(output->mBuffers[i].mData, 0,
			output->mBuffers[i].mDataByteSize);

	__atomic_store_n(&playCursor, cursor, __ATOMIC_RELEASE);
	return noErr;
}

qboolean SNDDMA_Init(void)
{
	AudioComponentDescription description;
	AudioComponent component;
	AudioStreamBasicDescription format;
	AURenderCallbackStruct callback;
	OSStatus status;
	int parameter;
	int speed;

	speed = desired_speed;
	parameter = COM_CheckParm("-sndspeed");
	if (parameter && parameter < com_argc - 1)
		speed = Q_atoi(com_argv[parameter + 1]);
	if (speed < 8000 || speed > 48000)
	{
		Con_Printf("Core Audio: invalid sample rate %d\n", speed);
		return false;
	}

	dmaBuffer = calloc(DMA_SAMPLE_COUNT, sizeof(short));
	if (!dmaBuffer)
	{
		Con_Printf("Core Audio: unable to allocate DMA buffer\n");
		return false;
	}

	memset((void *)&sn, 0, sizeof(sn));
	shm = &sn;
	shm->splitbuffer = false;
	shm->channels = 2;
	shm->samples = DMA_SAMPLE_COUNT;
	shm->submission_chunk = 1;
	shm->samplepos = 0;
	shm->samplebits = 16;
	shm->speed = speed;
	shm->buffer = dmaBuffer;
	shm->soundalive = true;
	shm->gamealive = true;
	__atomic_store_n(&playCursor, 0, __ATOMIC_RELEASE);

	memset(&description, 0, sizeof(description));
	description.componentType = kAudioUnitType_Output;
	description.componentSubType = kAudioUnitSubType_DefaultOutput;
	description.componentManufacturer = kAudioUnitManufacturer_Apple;
	component = AudioComponentFindNext(NULL, &description);
	if (!component)
	{
		Con_Printf("Core Audio: default output device is unavailable\n");
		goto failed;
	}

	status = AudioComponentInstanceNew(component, &outputUnit);
	if (status != noErr)
	{
		CoreAudioError("AudioComponentInstanceNew", status);
		goto failed;
	}

	memset(&format, 0, sizeof(format));
	format.mSampleRate = speed;
	format.mFormatID = kAudioFormatLinearPCM;
	format.mFormatFlags = kAudioFormatFlagIsSignedInteger |
		kAudioFormatFlagIsPacked | kAudioFormatFlagsNativeEndian;
	format.mBytesPerPacket = 4;
	format.mFramesPerPacket = 1;
	format.mBytesPerFrame = 4;
	format.mChannelsPerFrame = 2;
	format.mBitsPerChannel = 16;
	status = AudioUnitSetProperty(outputUnit, kAudioUnitProperty_StreamFormat,
		kAudioUnitScope_Input, 0, &format, sizeof(format));
	if (status != noErr)
	{
		CoreAudioError("setting stream format", status);
		goto failed;
	}

	callback.inputProc = CoreAudioRender;
	callback.inputProcRefCon = NULL;
	status = AudioUnitSetProperty(outputUnit, kAudioUnitProperty_SetRenderCallback,
		kAudioUnitScope_Input, 0, &callback, sizeof(callback));
	if (status != noErr)
	{
		CoreAudioError("setting render callback", status);
		goto failed;
	}

	status = AudioUnitInitialize(outputUnit);
	if (status != noErr)
	{
		CoreAudioError("AudioUnitInitialize", status);
		goto failed;
	}

	__atomic_store_n(&audioRunning, true, __ATOMIC_RELEASE);
	status = AudioOutputUnitStart(outputUnit);
	if (status != noErr)
	{
		__atomic_store_n(&audioRunning, false, __ATOMIC_RELEASE);
		CoreAudioError("AudioOutputUnitStart", status);
		goto failed;
	}

	Con_Printf("Core Audio initialized: %d Hz, 16-bit stereo\n", speed);
	return true;

failed:
	if (outputUnit)
	{
		AudioUnitUninitialize(outputUnit);
		AudioComponentInstanceDispose(outputUnit);
		outputUnit = NULL;
	}
	free(dmaBuffer);
	dmaBuffer = NULL;
	shm = NULL;
	return false;
}

int SNDDMA_GetDMAPos(void)
{
	uint32_t cursor;

	if (!__atomic_load_n(&audioRunning, __ATOMIC_ACQUIRE) || !shm)
		return 0;
	cursor = __atomic_load_n(&playCursor, __ATOMIC_ACQUIRE);
	shm->samplepos = cursor;
	return cursor;
}

void SNDDMA_Submit(void)
{
	/* Quake mixes directly into the circular buffer consumed by Core Audio. */
}

void SNDDMA_Shutdown(void)
{
	__atomic_store_n(&audioRunning, false, __ATOMIC_RELEASE);
	if (outputUnit)
	{
		AudioOutputUnitStop(outputUnit);
		AudioUnitUninitialize(outputUnit);
		AudioComponentInstanceDispose(outputUnit);
		outputUnit = NULL;
	}
	free(dmaBuffer);
	dmaBuffer = NULL;
}
