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

#include <unistd.h>

#include <pipewire/pipewire.h>

#include "src/shared/util.h"
#include "pwutil.h"

struct pipewire_ctx
{
	pid_t pids[2];
	struct pw_thread_loop *thread_loop;
	struct queue *jobs;
};

static pid_t launch_pw_prog(char *file, const char *xdg_runtime_dir)
{
	pid_t pid;
	char *argv[2];

	pid = fork();
	if (pid < 0)
		return pid;

	if (pid == 0) {
		argv[0] = file;
		argv[1] = NULL;

		setenv("XDG_RUNTIME_DIR", xdg_runtime_dir, 1);

		execvp(file, argv);
		exit(1);
	}

	return pid;
}

struct pipewire_ctx *pipewire_start(pipewire_complete_func_t cb,
						const char *xdg_runtime_dir)
{
	struct pipewire_ctx *ctx;

	ctx = new0(struct pipewire_ctx, 1);

	ctx->pids[0] = launch_pw_prog("pipewire", xdg_runtime_dir);
	ctx->pids[1] = launch_pw_prog("wireplumber", xdg_runtime_dir);

	return ctx;
}

void pipewire_teardown(struct pipewire_ctx *ctx)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(ctx->pids); ++i)
		if (ctx->pids[i] > 0)
			kill(ctx->pids[i], SIGTERM);

	free(ctx);
}
