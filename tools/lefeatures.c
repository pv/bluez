// SPDX-License-Identifier: GPL-2.0-or-later
/*
 *
 *  BlueZ - Bluetooth protocol stack for Linux
 *
 *  Copyright (C) 2011-2012  Intel Corporation
 *  Copyright (C) 2004-2010  Marcel Holtmann <marcel@holtmann.org>
 *
 *
 */

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include <getopt.h>

#include "lib/bluetooth.h"

#include "monitor/bt.h"
#include "src/shared/mainloop.h"
#include "src/shared/util.h"
#include "src/shared/hci.h"

static const char *le_feature_names[] = {
	[0] = "LE Encryption",
	[1] = "Connection Parameters Request Procedure",
	[2] = "Extended Reject Indication",
	[3] = "Slave-initiated Features Exchange",
	[4] = "LE Ping",
	[5] = "LE Data Packet Length Extension",
	[6] = "LL Privacy",
	[7] = "Extended Scanner Filter Policies",
	[8] = "LE 2M PH",
	[9] = "Stable Modulation Index - Transmitter",
	[10] = "Stable Modulation Index - Receiver",
	[11] = "LE Coded PH",
	[12] = "LE Extended Advertising",
	[13] = "LE Periodic Advertising",
	[14] = "Channel Selection Algorithm #2",
	[15] = "LE Power Class 1",
	[16] = "Minimum Number of Used Channels Procedure",
	[17] = "Connection CTE Request",
	[18] = "Connection CTE Response",
	[19] = "Connectionless CTE Transmitter",
	[20] = "Connectionless CTE Receiver",
	[21] = "Antenna Switching During CTE Transmission (AoD)",
	[22] = "Antenna Switching During CTE Reception (AoA)",
	[23] = "Receiving Constant Tone Extensions",
	[24] = "Periodic Advertising Sync Transfer - Sender",
	[25] = "Periodic Advertising Sync Transfer - Recipient",
	[26] = "Sleep Clock Accuracy Updates",
	[27] = "Remote Public Key Validation",
	[28] = "Connected Isochronous Stream - Master",
	[29] = "Connected Isochronous Stream - Slave",
	[30] = "Isochronous Broadcaster",
	[31] = "Synchronized Receiver",
	[32] = "Isochronous Channels (Host Support)",
	[33] = "LE Power Control Request",
	[34] = "LE Power Change Indication",
	[35] = "LE Path Loss Monitoring",
};

static void scan_le_features_callback(const void *data, uint8_t size,
							void *user_data)
{
	const struct bt_hci_rsp_le_read_local_features *rsp = data;
	int ibyte, ibit, pos;

	if (rsp->status) {
		fprintf(stderr, "Failed to read local LE features\n");
		mainloop_exit_failure();
		return;
	}

	for (ibyte = 0, pos = 0; ibyte < 8; ++ibyte) {
		fprintf(stderr, "le_features[%d] = 0x%02x\n", ibyte, (int)rsp->features[ibyte]);
	}
	for (ibyte = 0, pos = 0; ibyte < 8; ++ibyte) {
		for (ibit = 0; ibit < 8; ++ibit, ++pos) {
			const char *name = "RFU";

			if (pos < sizeof(le_feature_names) / sizeof(char *))
				name = le_feature_names[pos];

			fprintf(stderr, "bit %2d: %d (%s)\n",
					pos,
					(rsp->features[ibyte] & (0x1 << ibit)) ? 1 : 0,
					name);
		}
	}
	mainloop_quit();
}

static void signal_callback(int signum, void *user_data)
{
	switch (signum) {
	case SIGINT:
	case SIGTERM:
		mainloop_quit();
		break;
	}
}

static void usage(void)
{
	printf("lefeatures - Query LE features\n"
		"Usage:\n");
	printf("\tlefeatures [options] hciX\n");
	printf("options:\n"
		"\t-h, --help             Show help options\n");
}

static const struct option main_options[] = {
	{ "version",   no_argument,       NULL, 'v' },
	{ "help",      no_argument,       NULL, 'h' },
	{ }
};

static int parse_hci_index(char *str)
{
	char *end;
	long res;

	if (strncmp(str, "hci", 3) != 0)
		return -1;

	str += 3;

	res = strtol(str, &end, 10);
	if (*str != '\0' && *end == '\0')
		return res;

	return -1;
}

int main(int argc ,char *argv[])
{
	int exit_status;
	int index;
	static struct bt_hci *dev;
	char *dev_name = "hci0";

	for (;;) {
		int opt;

		opt = getopt_long(argc, argv, "vh", main_options, NULL);
		if (opt < 0)
			break;

		switch (opt) {
		case 'v':
			printf("%s\n", VERSION);
			return EXIT_SUCCESS;
		case 'h':
			usage();
			return EXIT_SUCCESS;
		default:
			return EXIT_FAILURE;
		}
	}

	if (argc - optind > 1) {
		fprintf(stderr, "Invalid command line parameters\n");
		return EXIT_FAILURE;
	}
	else if (argc - optind == 1)
		dev_name = argv[optind];

	mainloop_init();

	index = parse_hci_index(dev_name);
	if (index < 0) {
		fprintf(stderr, "Invalid hci device\n");
		return EXIT_FAILURE;
	}

	dev = bt_hci_new_user_channel(index);
	if (!dev) {
		fprintf(stderr, "Failed to open hci%d\n", index);
		return EXIT_FAILURE;
	}

	bt_hci_send(dev, BT_HCI_CMD_LE_READ_LOCAL_FEATURES, NULL, 0,
			scan_le_features_callback, NULL, NULL);

	exit_status = mainloop_run_with_signal(signal_callback, NULL);

	bt_hci_unref(dev);

	return exit_status;
}
