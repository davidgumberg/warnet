#!/bin/bash

warnet deploy networks/2_node_bitcoin
warnet bitcoin rpc miner createwallet "miner"
warnet bitcoin rpc miner -rpcwallet="miner" -generate 101
sleep 5
warnet bitcoin rpc tank2 createwallet "miner"
warnet bitcoin rpc tank2 -rpcwallet="miner" -generate 101
# warnet run scenarios/miner_std.py --tank=miner --mature --debug
warnet run scenarios/tx_flood.py

