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
typedef void (*pipewire_complete_func_t)(struct pipewire_ctx *ctx, int status,
					 const void *data);

struct pipewire_ctx *pipewire_start(pipewire_complete_func_t cb,
				    const char *xdg_runtime_dir);
void pipewire_teardown(struct pipewire_ctx *ctx);
