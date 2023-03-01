/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 *
 *  BlueZ - Bluetooth protocol stack for Linux
 *
 *  Copyright (C) 2022  Intel Corporation.
 *
 */

#ifndef __ISO_H
#define __ISO_H

#ifdef __cplusplus
extern "C" {
#endif

/* ISO defaults */
#define ISO_DEFAULT_MTU		251
#define ISO_MAX_NUM_BIS		0x1f

/* ISO socket broadcast address */
struct sockaddr_iso_bc {
	bdaddr_t	bc_bdaddr;
	uint8_t		bc_bdaddr_type;
	uint8_t		bc_sid;
	uint8_t		bc_num_bis;
	uint8_t		bc_bis[ISO_MAX_NUM_BIS];
};

/* ISO socket address */
struct sockaddr_iso {
	sa_family_t	iso_family;
	bdaddr_t	iso_bdaddr;
	uint8_t		iso_bdaddr_type;
	struct sockaddr_iso_bc iso_bc[];
};

/* ISO timing and packet information, both from packet completion and
 * LE Read ISO TX Sync, at a point of time immediately after completion
 * of the read sync command.
 */
struct bt_iso_tx_info_ctl {
	uint64_t	time;
	uint64_t	pkt_time;
	uint16_t	pkt_sn;
	uint16_t	pkt_queue;
	uint32_t	sync_timestamp;
	uint32_t	sync_offset;
	uint16_t	sync_sn;
};

#ifdef __cplusplus
}
#endif

#endif /* __ISO_H */
