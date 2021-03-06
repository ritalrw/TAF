import time
from dcp.constants import PRODUCER
from dcpbase import DCPBase
from membase.api.rest_client import RestConnection, RestHelper
from mc_bin_client import MemcachedError
from couchbase_helper.documentgenerator import doc_generator
from remote.remote_util import RemoteMachineShellConnection
from cb_tools.cbstats import Cbstats


class DCPRebalanceTests(DCPBase):
    def test_mutations_during_rebalance(self):
        # start rebalance
        task = self.cluster.async_rebalance([self.master], self.servers[1:],
                                            [])
        # load some data
        vbucket = 0
        self.load_docs(self.master, vbucket, self.num_items)
        shell_conn = RemoteMachineShellConnection(self.cluster.master)
        cb_stat_obj = Cbstats(self.log, shell_conn)
        # Fetch vbucket seqno stats
        vb_stat = cb_stat_obj.vbucket_seqno(self.bucket_util.buckets[0].name)
        # stream
        self.log.info("Streaming vb {0} to seqno {1}"
                      .format(vbucket, vb_stat[vbucket]["high_seqno"]))
        self.assertEquals(vb_stat[vbucket]["high_seqno"], self.num_items)

        dcp_client = self.dcp_client(self.master, PRODUCER, vbucket)
        stream = dcp_client.stream_req(vbucket, 0, 0,
                                       vb_stat[vbucket]["high_seqno"],
                                       vb_stat[vbucket]["uuid"])

        stream.run()
        last_seqno = stream.last_by_seqno
        assert last_seqno == vb_stat[vbucket]["high_seqno"], last_seqno

        # verify rebalance
        assert task.result()

    def test_failover_swap_rebalance(self):
        """ add and failover node then perform swap rebalance """

        assert len(self.servers) > 2, "not enough servers"
        nodeA = self.servers[0]
        nodeB = self.servers[1]
        nodeC = self.servers[2]

        gen_create = doc_generator('dcp', 0, self.num_items, doc_size=64)
        self._load_all_buckets(nodeA, gen_create, "create", 0)

        vbucket = 0

        # rebalance in nodeB
        assert self.cluster.rebalance([nodeA], [nodeB], [])

        # add nodeC
        rest = RestConnection(nodeB)
        rest.add_node(user=nodeC.rest_username, password=nodeC.rest_password,
                      remoteIp=nodeC.ip, port=nodeC.port)

        # stop and failover nodeA
        assert self.stop_node(0)
        self.stopped_nodes.append(0)
        self.master = nodeB

        assert self.cluster.failover([nodeB], [nodeA])
        try:
            assert self.cluster.rebalance([nodeB], [], [])
        except Exception:
            pass
        self.add_built_in_server_user()
        # verify seqnos and stream mutations
        rest = RestConnection(nodeB)
        total_mutations = 0

        # Create connection for CbStats
        shell_conn = RemoteMachineShellConnection(self.cluster.master)
        cb_stat_obj = Cbstats(shell_conn)
        vb_info = cb_stat_obj.vbucket_seqno(self.bucket_util.buckets[0].name)

        for vb in range(0, self.cluster_util.vbuckets):
            total_mutations += int(vb_info[vb]["high_seqno"])

        # Disconnect the Cbstats shell_conn
        shell_conn.disconnect()

        # / 2   # divide by because the items are split between 2 servers
        self.assertTrue(total_mutations == self.num_items,
                        msg="Number mismatch. {0} != {1}"
                        .format(total_mutations, self.num_items))

        task = self.cluster.async_rebalance([nodeB], [], [nodeC])
        task.result()

    def test_stream_req_during_failover(self):
        """
        stream_req mutations before and after failover
        from state-changing vbucket
        """

        # start rebalance
        try:
            self.cluster.rebalance([self.master], self.servers[1:], [])
        except Exception:
            pass

        vbucket = 0
        mcd_client = self.mcd_client(self.master, vbucket, auth_user=True)
        mcd_client.set('key1', 0, 0, 'value', vbucket)

        # failover node where key was set
        rest = RestConnection(self.master)
        index = self.vbucket_host_index(rest, vbucket)
        fail_n = self.servers[index]
        ready_n = filter(lambda n: n.ip != fail_n.ip or n.port != fail_n.port,
                         self.servers)

        assert self.stop_node(index)
        self.stopped_nodes.append(index)
        assert self.cluster.failover(ready_n, [fail_n])
        rebalance_t = self.cluster.async_rebalance(ready_n, [], [])

        # vbucket has moved, set another key in new location
        rest = RestConnection(ready_n[0])
        index = self.vbucket_host_index(rest, vbucket)
        new_master = ready_n[0]
        mcd_client = self.mcd_client(new_master, auth_user=True)
        try:
            mcd_client.set('key2', 0, 0, 'value', vbucket)
        except MemcachedError:
            self.sleep(10)
            mcd_client = self.mcd_client(new_master, auth_user=True)
            mcd_client.set('key2', 0, 0, 'value', vbucket)

        # stream mutation
        dcp_client = self.dcp_client(new_master, PRODUCER, vbucket)
        stream = dcp_client.stream_req(vbucket, 0, 0, 2, 0)

        while stream.has_response():

            response = stream.next_response()

            assert response is not None,\
                "Timeout reading stream after failover"

            if 'key' in response:
                if response['by_seqno'] == 1:
                    assert response['key'] == 'key1'
                elif response['by_seqno'] == 2:
                    assert response['key'] == 'key2'
                else:
                    assert False, "received unexpected mutation"

            # end
            if response['opcode'] == 0x55:
                break

        assert stream.last_by_seqno == 2
        assert rebalance_t.result()
        self.cluster.rebalance([new_master], [], ready_n[1:])

    def test_failover_log_table_updated(self):
        """
        Verifies failover table entries are updated when vbucket
        ownership changes
        """

        # rebalance in nodeB
        nodeA = self.servers[0]
        nodeB = self.servers[1]

        # load nodeA only
        rest = RestConnection(nodeA)
        vbuckets = rest.get_vbuckets()
        for vb_info in vbuckets[0:4]:
            vbucket = vb_info.id
            self.load_docs(nodeA, vbucket, self.num_items)

        # add nodeB
        self.cluster.rebalance([nodeA], [nodeB], [])

        # stop nodeA and failover
        assert self.stop_node(0)
        self.stopped_nodes.append(0)
        self.master = nodeB
        assert self.cluster.failover([nodeB], [nodeA])
        assert self.cluster.rebalance([nodeB], [], [])

        # load nodeB only
        rest = RestConnection(nodeB)
        vbuckets = rest.get_vbuckets()
        for vb_info in vbuckets[0:4]:
            vbucket = vb_info.id
            self.load_docs(nodeB, vbucket, self.num_items)

        # add nodeA back
        assert self.start_node(0)
        del self.stopped_nodes[0]
        rest = RestHelper(RestConnection(nodeA))
        assert rest.is_ns_server_running()
        time.sleep(10)
        self.cluster.rebalance([nodeB], [nodeA], [])

        # stop nodeB and failover
        assert self.stop_node(1)
        self.master = nodeA
        self.stopped_nodes.append(1)
        assert self.cluster.failover([nodeA], [nodeB])
        assert self.cluster.rebalance([nodeA], [], [])

        # load nodeA only
        rest = RestConnection(nodeA)
        vbuckets = rest.get_vbuckets()
        for vb_info in vbuckets[0:4]:
            vbucket = vb_info.id
            self.load_docs(nodeA, vbucket, self.num_items)

        # Create connection for CbStats
        shell_conn = RemoteMachineShellConnection(self.cluster.master)
        cb_stat_obj = Cbstats(shell_conn)

        # Fetch bucket's failover stats
        bucket = self.bucket_util.buckets[0]
        stats = cb_stat_obj.failover_stats(bucket.name)

        # Disconnect the Cbstats shell_conn
        shell_conn.disconnect()

        # Fetch vbucket seqno stats
        vb_stat = cb_stat_obj.vbucket_seqno(bucket.name)
        # Check failover table entries
        for vb_info in vbuckets[0:4]:
            vb = vb_info.id
            assert long(stats['vb_'+str(vb)+':num_entries']) == 2

            dcp_client = self.dcp_client(nodeA, PRODUCER)
            stream = dcp_client.stream_req(vb, 0, 0, self.num_items*3,
                                           vb_stat[vb]["uuid"])

            _ = stream.run()
            assert stream.last_by_seqno == self.num_items*3, \
                stream.last_by_seqno
