// SPDX-License-Identifier: LGPL-2.1-or-later
/*
 *
 *  BlueZ - Bluetooth protocol stack for Linux
 *
 *  Copyright (C) 2012-2014  Intel Corporation. All rights reserved.
 *
 *
 */

struct pipewire_ctx;
struct pipewire_wait;

#include <glib.h>

struct pipewire_ctx;
struct pipewire_wait;

#ifdef HAVE_PIPEWIRE

struct pipewire_ctx *pipewire_start(const char *runtime_dir);
void pipewire_exited(struct pipewire_ctx *ctx, pid_t pid);
void pipewire_stop(struct pipewire_ctx *ctx);

unsigned int pipewire_wait_node(struct pipewire_ctx *ctx,
				const char *node_name,
				unsigned int timeout_msec,
				GSourceOnceFunc callback,
				gpointer user_data);
void pipewire_wait_cancel(unsigned int wait_id);

#else

static inline struct pipewire_ctx *pipewire_start(pid_t *pw, pid_t *wp)
{
	*pw = -1;
	*wp = -1;
	return NULL;
}

static inline void pipewire_exited(struct pipewire_ctx *ctx, pid_t pid)
{
}

static inline void pipewire_stop(struct pipewire_ctx *ctx)
{
}

#endif
