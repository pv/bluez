// SPDX-License-Identifier: LGPL-2.1-or-later
/*
 *
 *  BlueZ - Bluetooth protocol stack for Linux
 *
 *  Copyright (C) 2012-2014  Intel Corporation. All rights reserved.
 *
 *
 */

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include <pipewire/pipewire.h>

#include "pwutil.h"

struct pipewire_ctx
{
	pid_t pipewire_pid;
	pid_t wireplumber_pid;
	struct pw_thread_loop *thread_loop;
	struct queue *jobs;
};

struct pipewire_ctx *pipewire_start(pipewire_complete_func_t cb);

void pipewire_teardown(struct pipewire_ctx *ctx);
