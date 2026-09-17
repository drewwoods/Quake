/*
This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

*/
// cd_file.c -- file-backed replacement for CD audio

#include "quakedef.h"
#include <limits.h>

#define	CD_SAMPLE_RATE		44100
#define	CD_SAMPLE_BITS		16
#define	CD_CHANNELS		2
#define	CD_PCM_FORMAT_TAG	1
#define	CD_FRAME_BYTES		4
#define	CD_BYTE_RATE		(CD_SAMPLE_RATE * CD_FRAME_BYTES)
#define	CD_BUFFER_BYTES		16384
#define	CD_MAX_TRACK		255

static FILE		*cd_file;
static byte		cd_buffer[CD_BUFFER_BYTES];
static int		cd_buffer_pos;
static int		cd_buffer_bytes;
static int		cd_data_pos;
static int		cd_data_bytes;
static long		cd_data_file_offset;
static byte		cd_track;
static qboolean	cd_initialized;
static qboolean	cd_enabled;
static qboolean	cd_playing;
static qboolean	cd_paused;
static qboolean	cd_looping;


/*
================
CDAudio_ReadLE16
================
*/
static unsigned int CDAudio_ReadLE16(byte *data)
{
	return (unsigned int)data[0] | ((unsigned int)data[1] << 8);
}


/*
================
CDAudio_ReadLE32
================
*/
static unsigned long CDAudio_ReadLE32(byte *data)
{
	return (unsigned long)data[0]
		| ((unsigned long)data[1] << 8)
		| ((unsigned long)data[2] << 16)
		| ((unsigned long)data[3] << 24);
}


/*
================
CDAudio_ReadBytes

Keep reads inside the COM_FOpenMusicFile entry, including PAK entries.
================
*/
static qboolean CDAudio_ReadBytes(FILE *file, byte *data, int bytes,
	unsigned long *position, unsigned long limit)
{
	if (bytes < 0 || *position > limit
		|| (unsigned long)bytes > limit - *position)
		return false;

	if (bytes && fread(data, 1, (size_t)bytes, file) != (size_t)bytes)
		return false;

	*position += (unsigned long)bytes;
	return true;
}


/*
================
CDAudio_SkipBytes
================
*/
static qboolean CDAudio_SkipBytes(FILE *file, unsigned long bytes,
	unsigned long *position, unsigned long limit)
{
	if (*position > limit || bytes > limit - *position || bytes > LONG_MAX)
		return false;
	if (bytes && fseek(file, (long)bytes, SEEK_CUR))
		return false;
	*position += bytes;

	return true;
}


/*
================
CDAudio_ParseWave
================
*/
static qboolean CDAudio_ParseWave(FILE *file, int file_length,
	long file_start, long *data_offset, int *data_length)
{
	byte		header[12];
	byte		chunk[8];
	byte		format[16];
	unsigned long	position;
	unsigned long	riff_size;
	unsigned long	riff_end;
	unsigned long	chunk_size;
	unsigned long	chunk_data;
	unsigned long	data_start;
	unsigned int	block_align;
	unsigned int	channels;
	unsigned int	format_tag;
	unsigned int	bits_per_sample;
	unsigned long	byte_rate;
	unsigned long	sample_rate;
	qboolean	have_format;
	qboolean	have_data;

	if (file_length < 12)
		return false;

	position = 0;
	if (!CDAudio_ReadBytes(file, header, sizeof(header), &position,
		(unsigned long)file_length))
		return false;
	if (Q_memcmp(header, "RIFF", 4) || Q_memcmp(header + 8, "WAVE", 4))
		return false;

	riff_size = CDAudio_ReadLE32(header + 4);
	if (riff_size < 4 || riff_size > (unsigned long)file_length - 8)
		return false;
	riff_end = 8 + riff_size;
	have_format = false;
	have_data = false;

	while (position < riff_end)
	{
		if (riff_end - position < sizeof(chunk))
			return false;
		if (!CDAudio_ReadBytes(file, chunk, sizeof(chunk), &position, riff_end))
			return false;

		chunk_size = CDAudio_ReadLE32(chunk + 4);
		chunk_data = position;
		if (chunk_size > riff_end - chunk_data)
			return false;

		if (!Q_memcmp(chunk, "fmt ", 4))
		{
			if (have_format || chunk_size < sizeof(format))
				return false;
			if (!CDAudio_ReadBytes(file, format, sizeof(format), &position,
				riff_end))
				return false;

			format_tag = CDAudio_ReadLE16(format + 0);
			channels = CDAudio_ReadLE16(format + 2);
			sample_rate = CDAudio_ReadLE32(format + 4);
			byte_rate = CDAudio_ReadLE32(format + 8);
			block_align = CDAudio_ReadLE16(format + 12);
			bits_per_sample = CDAudio_ReadLE16(format + 14);
			if (format_tag != CD_PCM_FORMAT_TAG || channels != CD_CHANNELS
				|| sample_rate != CD_SAMPLE_RATE
				|| bits_per_sample != CD_SAMPLE_BITS
				|| block_align != CD_FRAME_BYTES
				|| byte_rate != CD_BYTE_RATE)
				return false;

			have_format = true;
			if (!CDAudio_SkipBytes(file, chunk_size - sizeof(format),
				&position, riff_end))
				return false;
		}
		else if (!Q_memcmp(chunk, "data", 4))
		{
			if (have_data || chunk_size == 0 || chunk_size % CD_FRAME_BYTES)
				return false;
			if (chunk_data > (unsigned long)LONG_MAX
				|| file_start > LONG_MAX - (long)chunk_data
				|| chunk_size > (unsigned long)Q_MAXINT)
				return false;
			data_start = chunk_data;
			*data_offset = file_start + (long)data_start;
			*data_length = (int)chunk_size;
			have_data = true;
			if (!CDAudio_SkipBytes(file, chunk_size, &position, riff_end))
				return false;
		}
		else if (!CDAudio_SkipBytes(file, chunk_size, &position, riff_end))
			return false;

		if (chunk_size & 1)
		{
			if (!CDAudio_SkipBytes(file, 1, &position, riff_end))
				return false;
		}
	}

	if (!have_format || !have_data || position != riff_end)
		return false;
	if (fseek(file, *data_offset, SEEK_SET))
		return false;

	return true;
}


/*
================
CDAudio_FillBuffer
================
*/
static qboolean CDAudio_FillBuffer(void)
{
	int		want;
	int		count;
	int		bytes_read;

	if (cd_data_pos >= cd_data_bytes)
		return false;

	want = cd_data_bytes - cd_data_pos;
	if (want > CD_BUFFER_BYTES)
		want = CD_BUFFER_BYTES;
	want -= want % CD_FRAME_BYTES;
	if (want <= 0)
		return false;

	bytes_read = 0;
	while (bytes_read < want)
	{
		count = (int)fread(cd_buffer + bytes_read, 1,
			(size_t)(want - bytes_read), cd_file);
		if (count <= 0)
			return false;
		bytes_read += count;
	}

	cd_buffer_pos = 0;
	cd_buffer_bytes = bytes_read;
	cd_data_pos += bytes_read;
	return true;
}


/*
================
CDAudio_OutputReady
================
*/
static qboolean CDAudio_OutputReady(void)
{
	if (shm && shm->speed == CD_SAMPLE_RATE
		&& shm->samplebits == CD_SAMPLE_BITS
		&& shm->channels == CD_CHANNELS)
		return true;

	Con_Printf("CDAudio: requires 44100 Hz, stereo, 16-bit output; use -sndspeed 44100\n");
	return false;
}


/*
================
CDAudio_Volume
================
*/
static float CDAudio_Volume(void)
{
	float		value;

	value = bgmvolume.value;
	if (!(value > 0.0f))
		return 0.0f;
	if (value > 1.0f)
		return 1.0f;
	return value;
}


/*
================
CD_f
================
*/
static void CD_f(void)
{
	char *command;
	int		track;

	if (!cd_initialized || Cmd_Argc() < 2)
		return;

	command = Cmd_Argv(1);
	if (!Q_strcasecmp(command, "on"))
	{
		cd_enabled = true;
		return;
	}
	if (!Q_strcasecmp(command, "off"))
	{
		CDAudio_Stop();
		cd_enabled = false;
		return;
	}
	if (!Q_strcasecmp(command, "stop"))
	{
		CDAudio_Stop();
		return;
	}
	if (!Q_strcasecmp(command, "pause"))
	{
		CDAudio_Pause();
		return;
	}
	if (!Q_strcasecmp(command, "resume"))
	{
		CDAudio_Resume();
		return;
	}
	if (!Q_strcasecmp(command, "play") || !Q_strcasecmp(command, "loop"))
	{
		if (Cmd_Argc() < 3)
			return;
		track = Q_atoi(Cmd_Argv(2));
		if (track < 0 || track > CD_MAX_TRACK)
		{
			CDAudio_Stop();
			Con_DPrintf("CDAudio: bad track number %i\n", track);
			return;
		}
		CDAudio_Play((byte)track, !Q_strcasecmp(command, "loop"));
		return;
	}
	if (!Q_strcasecmp(command, "info"))
	{
		Con_Printf("CD Audio: %s\n", cd_enabled ? "on" : "off");
		if (cd_file)
			Con_Printf("Track %u: %s%s\n", cd_track,
				cd_paused ? "paused" : "playing",
				cd_looping ? ", looping" : "");
		return;
	}
}


/*
================
CDAudio_Paint
================
*/
void CDAudio_Paint(portable_samplepair_t *buffer, int frames)
{
	float		volume;
	int		left;
	int		right;

	if (!cd_enabled || !cd_playing || !cd_file || !buffer || frames <= 0)
		return;

	volume = CDAudio_Volume();
	while (frames--)
	{
		if (cd_buffer_pos >= cd_buffer_bytes)
		{
			if (cd_data_pos >= cd_data_bytes)
			{
				if (!cd_looping)
				{
					CDAudio_Stop();
					return;
				}
				if (fseek(cd_file, cd_data_file_offset, SEEK_SET))
				{
					CDAudio_Stop();
					return;
				}
				cd_data_pos = 0;
			}
			if (!CDAudio_FillBuffer())
			{
				CDAudio_Stop();
				return;
			}
		}

		left = (short)CDAudio_ReadLE16(cd_buffer + cd_buffer_pos);
		right = (short)CDAudio_ReadLE16(cd_buffer + cd_buffer_pos + 2);
		buffer->left += (int)((float)left * volume);
		buffer->right += (int)((float)right * volume);
		buffer++;
		cd_buffer_pos += CD_FRAME_BYTES;
	}
}


/*
================
CDAudio_Play
================
*/
void CDAudio_Play(byte track, qboolean looping)
{
	char path[MAX_QPATH];
	FILE		*file;
	int		file_length;
	long		file_start;
	long		data_offset;
	int		data_length;

	if (!cd_initialized || !cd_enabled)
		return;
	if (!CDAudio_OutputReady())
		return;
	if (cd_file && cd_track == track && (cd_playing || cd_paused))
		return;

	CDAudio_Stop();
	if (!track)
	{
		Con_DPrintf("CDAudio: bad track number 0\n");
		return;
	}

	snprintf(path, sizeof(path), "music/track%02u.wav", (unsigned int)track);
	file = NULL;
	file_length = COM_FOpenMusicFile(path, &file);
	if (!file || file_length <= 0)
	{
		if (file)
			fclose(file);
		Con_DPrintf("CDAudio: couldn't open %s\n", path);
		return;
	}

	file_start = ftell(file);
	if (file_start < 0
		|| !CDAudio_ParseWave(file, file_length, file_start,
			&data_offset, &data_length))
	{
		fclose(file);
		Con_DPrintf("CDAudio: invalid WAV %s\n", path);
		return;
	}

	cd_file = file;
	cd_data_file_offset = data_offset;
	cd_data_bytes = data_length;
	cd_data_pos = 0;
	cd_buffer_pos = 0;
	cd_buffer_bytes = 0;
	cd_track = track;
	cd_looping = looping;
	cd_paused = false;
	cd_playing = true;
}


/*
================
CDAudio_Stop
================
*/
void CDAudio_Stop(void)
{
	if (cd_file)
	{
		fclose(cd_file);
		cd_file = NULL;
	}
	cd_buffer_pos = 0;
	cd_buffer_bytes = 0;
	cd_data_pos = 0;
	cd_data_bytes = 0;
	cd_data_file_offset = 0;
	cd_track = 0;
	cd_playing = false;
	cd_paused = false;
	cd_looping = false;
}

void CDAudio_Pause(void)
{
	if (!cd_enabled || !cd_playing || !cd_file)
		return;
	cd_playing = false;
	cd_paused = true;
}


void CDAudio_Resume(void)
{
	if (!cd_enabled || !cd_paused || !cd_file)
		return;
	cd_paused = false;
	cd_playing = true;
}


void CDAudio_Update(void)
{
}


int CDAudio_Init(void)
{
	CDAudio_Stop();
	cd_initialized = false;
	cd_enabled = false;

	if (cls.state == ca_dedicated || COM_CheckParm("-nocdaudio"))
		return -1;

	cd_initialized = true;
	cd_enabled = true;
	Cmd_AddCommand("cd", CD_f);
	Con_Printf("CD Audio Initialized\n");
	return 0;
}


void CDAudio_Shutdown(void)
{
	CDAudio_Stop();
	cd_enabled = false;
	cd_initialized = false;
}
