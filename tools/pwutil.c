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

#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>

#include <glib.h>

#include <pipewire/pipewire.h>
#include <pipewire/extensions/metadata.h>

#include "src/shared/util.h"
#include "pwutil.h"

#define TIMEOUT_SECS	3

struct pipewire_ctx
{
	pid_t pids[2];
	struct pw_thread_loop *loop;

	struct pw_context *context;
	struct pw_core *core;
	struct pw_registry *registry;
	struct spa_hook registry_listener;
	struct spa_list object_list;
	struct spa_list pending_list;

	unsigned int wait_id;
	bool wait_start;
};

struct object
{
	struct spa_list link;
	struct pipewire_ctx *ctx;
	uint32_t id;
	char *type;
	struct pw_properties *props;
};

struct pending
{
	struct spa_list link;
	struct pipewire_ctx *ctx;
	unsigned int id;
	char *type;
	char *name;
	GSourceFunc func;
	gpointer user_data;
	struct spa_source *timeout;
};

static pid_t launch_pw_prog(char *file, const char *runtime_dir)
{
	pid_t pid;
	char *argv[2];

	pid = fork();
	if (pid < 0)
		return pid;

	if (pid == 0) {
		argv[0] = file;
		argv[1] = NULL;

		setenv("PIPEWIRE_RUNTIME_DIR", runtime_dir, 1);

		execvp(file, argv);
		exit(1);
	}

	return pid;
}

static void object_destroy(struct object *o)
{
	spa_list_remove(&o->link);
	free(o->type);
	pw_properties_free(o->props);
	free(o);
}

static void pending_destroy(struct pending *p)
{
	spa_list_remove(&p->link);
	pw_loop_destroy_source(pw_thread_loop_get_loop(p->ctx->loop), p->timeout);
	free(p->name);
	free(p);
}

static bool pending_match(struct pending *p, struct object *o)
{
	return spa_streq(p->type, o->type) && o->props &&
		spa_streq(p->name, pw_properties_get(o->props, PW_KEY_NODE_NAME));
}

static void check_pending(struct pipewire_ctx *ctx)
{
	struct object *o;
	struct pending *p, *tmp;

	spa_list_for_each_safe(p, tmp, &ctx->pending_list, link) {
		spa_list_for_each(o, &ctx->object_list, link) {
			if (!pending_match(p, o))
				continue;

			g_idle_add(p->func, p->user_data);
			pending_destroy(p);
		}
	}
}

static void registry_event_global(void *data, uint32_t id,
                uint32_t permissions, const char *type, uint32_t version,
                const struct spa_dict *props)
{
	struct pipewire_ctx *ctx = data;
	struct object *o;

	spa_list_for_each(o, &ctx->object_list, link) {
		if (o->id == id)
			return;
	}

	o = new0(struct object, 1);
	o->ctx = ctx;
	o->id = id;
	o->type = strdup(type);
	o->props = props ? pw_properties_new_dict(props) : NULL;

	spa_list_append(&ctx->object_list, &o->link);

	if (ctx->wait_start) {
		if (spa_streq(type, PW_TYPE_INTERFACE_Metadata)) {
			ctx->wait_start = false;
			pw_thread_loop_signal(ctx->loop, false);
		}
	}

	check_pending(ctx);
}

static void registry_event_global_remove(void *data, uint32_t id)
{
	struct pipewire_ctx *ctx = data;
	struct object *o;

	spa_list_for_each(o, &ctx->object_list, link) {
		if (o->id == id) {
			object_destroy(o);
			return;
		}
	}
}

static const struct pw_registry_events registry_events = {
        PW_VERSION_REGISTRY_EVENTS,
        .global = registry_event_global,
        .global_remove = registry_event_global_remove,
};

struct pipewire_wait *pipewire_wait_node(struct pipewire_ctx *ctx,
					 const char *node_name,
					 unsigned int timeout_msec,
					 GSourceFunc callback,
					 gpointer user_data)
{
	struct pending *p = pi
}

void pipewire_wait_cancel(unsigned int id)
{
	struct pending *p, *tmp;

	pw_thread_loop_lock(p->ctx->loop);

	spa_list_for_each_safe(p, tmp, &p->ctx->pending_list, link)
		if (p->id == id)
			pending_destroy(p);

	pw_thread_loop_unlock(p->ctx->loop);
}

struct pipewire_ctx *pipewire_start(const char *runtime_dir)
{
	struct pipewire_ctx *ctx;
	int i;

	setenv("PIPEWIRE_RUNTIME_DIR", runtime_dir, 1);

	pw_init(NULL, NULL);

	ctx = new0(struct pipewire_ctx, 1);
	ctx->wait_start = true;
	spa_list_init(&ctx->object_list);

	ctx->pids[0] = launch_pw_prog("pipewire", runtime_dir);
	ctx->pids[1] = launch_pw_prog("wireplumber", runtime_dir);

	if (ctx->pids[0] < 0 || ctx->pids[1] < 0)
		goto fail;

	ctx->loop = pw_thread_loop_new("main", NULL);
	pw_thread_loop_lock(ctx->loop);
	pw_thread_loop_start(ctx->loop);

	ctx->context = pw_context_new(pw_thread_loop_get_loop(ctx->loop), NULL, 0);

	/* Connect */
	i = 0;
	while (1) {
		ctx->core = pw_context_connect(ctx->context, NULL, 0);
		if (!ctx->core && i < 2*TIMEOUT_SECS) {
			usleep(500);
			++i;
			continue;
		}
		break;
	}

	if (!ctx->core)
		goto fail;

	/* Wait until ready */
	ctx->registry = pw_core_get_registry(ctx->core, PW_VERSION_REGISTRY, 0);

	pw_registry_add_listener(ctx->registry, &ctx->registry_listener,
			&registry_events, ctx);

	pw_thread_loop_timed_wait(ctx->loop, TIMEOUT_SECS);
	if (ctx->wait_start)
		goto fail;

	pw_thread_loop_unlock(ctx->loop);
	return ctx;

fail:
	if (ctx->loop)
		pw_thread_loop_unlock(ctx->loop);
	pipewire_stop(ctx);
	return NULL;
}

void pipewire_exited(struct pipewire_ctx *ctx, pid_t pid)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(ctx->pids); ++i)
		if (ctx->pids[i] == pid)
			ctx->pids[i] = -1;
}

void pipewire_stop(struct pipewire_ctx *ctx)
{
	int i;

	if (ctx->loop) {
		struct object *o;
		struct pending *p;

		pw_thread_loop_lock(ctx->loop);

		spa_list_consume(o, &ctx->object_list, link)
			object_destroy(o);
		spa_list_consume(p, &ctx->pending_list, link)
			pending_destroy(p);

		pw_thread_loop_unlock(ctx->loop);
		pw_thread_loop_stop(ctx->loop);
		if (ctx->registry)
			pw_proxy_destroy((struct pw_proxy *)ctx->registry);
		if (ctx->core)
			pw_core_disconnect(ctx->core);
		pw_context_destroy(ctx->context);
		pw_thread_loop_destroy(ctx->loop);
	}

	pw_deinit();

	for (i = 0; i < ARRAY_SIZE(ctx->pids); ++i) {
		int ret, status;

		if (ctx->pids[i] <= 0)
			continue;

		ret = waitpid(ctx->pids[i], &status, WNOHANG);
		if (ret > 0 && (WIFEXITED(status) || WIFSIGNALED(status)))
			ctx->pids[i] = -1;

		if (ctx->pids[i] >= 0)
			kill(ctx->pids[i], SIGTERM);
	}

	free(ctx);
}
