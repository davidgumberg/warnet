#!/bin/bash

warnet deploy networks/2_node_bitcoin
warnet run scenarios/miner_std.py --tank=miner
warnet run scenarios/tx_flood.py 

