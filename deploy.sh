#!/bin/bash

warnet deploy networks/2_node_bitcoin
sleep 5
warnet bitcoin rpc miner createwallet "miner"
warnet bitcoin rpc miner -rpcwallet="miner" -generate 101
warnet bitcoin rpc tank2 createwallet "tank2"
warnet bitcoin rpc tank2 -rpcwallet="tank2" -generate 101
# warnet run scenarios/miner_std.py --tank=miner --mature --debug
warnet run scenarios/tx_flood.py  --debug

