#!/bin/bash

warnet deploy networks/2_node_bitcoin
sleep 30
warnet run scenarios/miner_std.py --interval 5 --allnodes --mature --once
#warnet run scenarios/tx_flood.py --interval 0.1
sleep 10 && warnet dashboard
