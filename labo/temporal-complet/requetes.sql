-- cluster_metadata.insertClusterMetadataQry
INSERT INTO cluster_metadata_info (metadata_partition, cluster_name, data, data_encoding, version) VALUES($1, $2, $3, $4, $5)

-- cluster_metadata.updateClusterMetadataQry
UPDATE cluster_metadata_info SET data = $1, data_encoding = $2, version = $3 WHERE metadata_partition = $4 AND cluster_name = $5

-- cluster_metadata.deleteClusterMetadataQry
DELETE FROM cluster_metadata_info WHERE metadata_partition = $1 AND cluster_name = $2

-- cluster_metadata.templateUpsertActiveClusterMembership
INSERT INTO cluster_membership (membership_partition, host_id, rpc_address, rpc_port, role, session_start, last_heartbeat, record_expiry) VALUES($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT(membership_partition, host_id) DO UPDATE SET membership_partition = $1, host_id = $2, rpc_address = $3, rpc_port = $4, role = $5, session_start = $6, last_heartbeat = $7, record_expiry = $8

-- cluster_metadata.templatePruneStaleClusterMembership
DELETE FROM cluster_membership WHERE host_id = ANY(ARRAY( SELECT host_id FROM cluster_membership WHERE membership_partition = $1 AND record_expiry < $2))

-- events.getHistoryNodesQuery
SELECT node_id, prev_txn_id, txn_id, data, data_encoding FROM history_node WHERE shard_id = $1 AND tree_id = $2 AND branch_id = $3 AND ((node_id = $4 AND txn_id > $5) OR node_id > $6) AND node_id < $7 ORDER BY shard_id, tree_id, branch_id, node_id, txn_id LIMIT $8

-- events.getHistoryNodesReverseQuery
SELECT node_id, prev_txn_id, txn_id, data, data_encoding FROM history_node WHERE shard_id = $1 AND tree_id = $2 AND branch_id = $3 AND node_id >= $4 AND ((node_id = $5 AND txn_id < $6) OR node_id < $7) ORDER BY shard_id, tree_id, branch_id DESC, node_id DESC, txn_id DESC LIMIT $8

-- events.getHistoryNodeMetadataQuery
SELECT node_id, prev_txn_id, txn_id FROM history_node WHERE shard_id = $1 AND tree_id = $2 AND branch_id = $3 AND ((node_id = $4 AND txn_id > $5) OR node_id > $6) AND node_id < $7 ORDER BY shard_id, tree_id, branch_id, node_id, txn_id LIMIT $8

-- events.deleteHistoryNodeQuery
DELETE FROM history_node WHERE shard_id = $1 AND tree_id = $2 AND branch_id = $3 AND node_id = $4 AND txn_id = $5

-- events.deleteHistoryNodesQuery
DELETE FROM history_node WHERE shard_id = $1 AND tree_id = $2 AND branch_id = $3 AND node_id >= $4

-- events.getHistoryTreeQuery
SELECT branch_id, data, data_encoding FROM history_tree WHERE shard_id = $1 AND tree_id = $2

-- events.paginateBranchesQuery
SELECT shard_id, tree_id, branch_id, data, data_encoding FROM history_tree WHERE (shard_id, tree_id, branch_id) > ($1, $2, $3) ORDER BY shard_id, tree_id, branch_id LIMIT $4

-- events.deleteHistoryTreeQuery
DELETE FROM history_tree WHERE shard_id = $1 AND tree_id = $2 AND branch_id = $3

-- execution.deleteExecutionQuery
DELETE FROM executions WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution.lockExecutionQueryBase
SELECT db_record_version, next_event_id FROM executions WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution.getCurrentExecutionQuery
SELECT shard_id, namespace_id, workflow_id, run_id, create_request_id, state, status, start_time, last_write_version, data, data_encoding FROM current_executions WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3

-- execution.getCurrentChasmExecutionQuery
SELECT shard_id, namespace_id, business_id as workflow_id, run_id, create_request_id, state, status, start_time, last_write_version, data, data_encoding FROM current_chasm_executions WHERE shard_id = $1 AND namespace_id = $2 AND business_id = $3 AND archetype_id = $4

-- execution.lockCurrentExecutionJoinExecutionsQuery
SELECT ce.shard_id, ce.namespace_id, ce.workflow_id, ce.run_id, ce.create_request_id, ce.state, ce.status, ce.start_time, e.last_write_version, ce.data, ce.data_encoding FROM current_executions ce INNER JOIN executions e ON e.shard_id = ce.shard_id AND e.namespace_id = ce.namespace_id AND e.workflow_id = ce.workflow_id AND e.run_id = ce.run_id WHERE ce.shard_id = $1 AND ce.namespace_id = $2 AND ce.workflow_id = $3 FOR UPDATE

-- execution.lockCurrentChasmExecutionJoinExecutionsQuery
SELECT ce.shard_id, ce.namespace_id, ce.business_id as workflow_id, ce.run_id, ce.create_request_id, ce.state, ce.status, ce.start_time, e.last_write_version, ce.data, ce.data_encoding FROM current_chasm_executions ce INNER JOIN executions e ON e.shard_id = ce.shard_id AND e.namespace_id = ce.namespace_id AND e.workflow_id = ce.business_id AND e.run_id = ce.run_id WHERE ce.shard_id = $1 AND ce.namespace_id = $2 AND ce.business_id = $3 AND ce.archetype_id = $4 FOR UPDATE

-- execution.getHistoryImmediateTasksQuery
SELECT task_id, data, data_encoding FROM history_immediate_tasks WHERE shard_id = $1 AND category_id = $2 AND task_id >= $3 AND task_id < $4 ORDER BY task_id LIMIT $5

-- execution.deleteHistoryImmediateTaskQuery
DELETE FROM history_immediate_tasks WHERE shard_id = $1 AND category_id = $2 AND task_id = $3

-- execution.rangeDeleteHistoryImmediateTasksQuery
DELETE FROM history_immediate_tasks WHERE shard_id = $1 AND category_id = $2 AND task_id >= $3 AND task_id < $4

-- execution.getHistoryScheduledTasksQuery
SELECT visibility_timestamp, task_id, data, data_encoding FROM history_scheduled_tasks WHERE shard_id = $1 AND category_id = $2 AND ((visibility_timestamp >= $3 AND task_id >= $4) OR visibility_timestamp > $5) AND visibility_timestamp < $6 ORDER BY visibility_timestamp,task_id LIMIT $7

-- execution.deleteHistoryScheduledTaskQuery
DELETE FROM history_scheduled_tasks WHERE shard_id = $1 AND category_id = $2 AND visibility_timestamp = $3 AND task_id = $4

-- execution.rangeDeleteHistoryScheduledTasksQuery
DELETE FROM history_scheduled_tasks WHERE shard_id = $1 AND category_id = $2 AND visibility_timestamp >= $3 AND visibility_timestamp < $4

-- execution.getTransferTasksQuery
SELECT task_id, data, data_encoding FROM transfer_tasks WHERE shard_id = $1 AND task_id >= $2 AND task_id < $3 ORDER BY task_id LIMIT $4

-- execution.deleteTransferTaskQuery
DELETE FROM transfer_tasks WHERE shard_id = $1 AND task_id = $2

-- execution.rangeDeleteTransferTaskQuery
DELETE FROM transfer_tasks WHERE shard_id = $1 AND task_id >= $2 AND task_id < $3

-- execution.getTimerTasksQuery
SELECT visibility_timestamp, task_id, data, data_encoding FROM timer_tasks WHERE shard_id = $1 AND ((visibility_timestamp >= $2 AND task_id >= $3) OR visibility_timestamp > $4) AND visibility_timestamp < $5 ORDER BY visibility_timestamp,task_id LIMIT $6

-- execution.deleteTimerTaskQuery
DELETE FROM timer_tasks WHERE shard_id = $1 AND visibility_timestamp = $2 AND task_id = $3

-- execution.rangeDeleteTimerTaskQuery
DELETE FROM timer_tasks WHERE shard_id = $1 AND visibility_timestamp >= $2 AND visibility_timestamp < $3

-- execution.getReplicationTasksQuery
SELECT task_id, data, data_encoding FROM replication_tasks WHERE shard_id = $1 AND task_id >= $2 AND task_id < $3 ORDER BY task_id LIMIT $4

-- execution.deleteReplicationTaskQuery
DELETE FROM replication_tasks WHERE shard_id = $1 AND task_id = $2

-- execution.rangeDeleteReplicationTaskQuery
DELETE FROM replication_tasks WHERE shard_id = $1 AND task_id >= $2 AND task_id < $3

-- execution.getReplicationTasksDLQQuery
SELECT task_id, data, data_encoding FROM replication_tasks_dlq WHERE source_cluster_name = $1 AND shard_id = $2 AND task_id >= $3 AND task_id < $4 ORDER BY task_id LIMIT $5

-- execution.getVisibilityTasksQuery
SELECT task_id, data, data_encoding FROM visibility_tasks WHERE shard_id = $1 AND task_id >= $2 AND task_id < $3 ORDER BY task_id LIMIT $4

-- execution.deleteVisibilityTaskQuery
DELETE FROM visibility_tasks WHERE shard_id = $1 AND task_id = $2

-- execution.rangeDeleteVisibilityTaskQuery
DELETE FROM visibility_tasks WHERE shard_id = $1 AND task_id >= $2 AND task_id < $3

-- execution.deleteBufferedEventsQuery
DELETE FROM buffered_events WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution.getBufferedEventsQuery
SELECT data, data_encoding FROM buffered_events WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4 ORDER BY id

-- execution.deleteReplicationTaskFromDLQQuery
DELETE FROM replication_tasks_dlq WHERE source_cluster_name = $1 AND shard_id = $2 AND task_id = $3

-- execution.rangeDeleteReplicationTaskFromDLQQuery
DELETE FROM replication_tasks_dlq WHERE source_cluster_name = $1 AND shard_id = $2 AND task_id >= $3 AND task_id < $4

-- execution_maps.deleteMapQueryTemplate[activity_info_maps]
DELETE FROM activity_info_maps WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution_maps.deleteMapQueryTemplate[timer_info_maps]
DELETE FROM timer_info_maps WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution_maps.deleteMapQueryTemplate[child_execution_info_maps]
DELETE FROM child_execution_info_maps WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution_maps.deleteMapQueryTemplate[request_cancel_info_maps]
DELETE FROM request_cancel_info_maps WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution_maps.deleteMapQueryTemplate[signal_info_maps]
DELETE FROM signal_info_maps WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution_maps.deleteMapQueryTemplate[chasm_node_maps]
DELETE FROM chasm_node_maps WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution_maps.deleteAllSignalsRequestedSetQuery
DELETE FROM signals_requested_sets WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- execution_maps.getSignalsRequestedSetQuery
SELECT signal_id FROM signals_requested_sets WHERE shard_id = $1 AND namespace_id = $2 AND workflow_id = $3 AND run_id = $4

-- namespace.createNamespaceQuery
INSERT INTO namespaces (partition_id, id, name, is_global, data, data_encoding, notification_version) VALUES($1, $2, $3, $4, $5, $6, $7)

-- namespace.updateNamespaceQuery
UPDATE namespaces SET name = $1, data = $2, data_encoding = $3, is_global = $4, notification_version = $5 WHERE partition_id=54321 AND id = $6

-- namespace.deleteNamespaceByIDQuery
DELETE FROM namespaces WHERE partition_id=$1 AND id = $2

-- namespace.deleteNamespaceByNameQuery
DELETE FROM namespaces WHERE partition_id=$1 AND name = $2

-- namespace.getNamespaceMetadataQuery
SELECT notification_version FROM namespace_metadata WHERE partition_id=$1

-- namespace.lockNamespaceMetadataQuery
SELECT notification_version FROM namespace_metadata WHERE partition_id=$1 FOR UPDATE

-- namespace.updateNamespaceMetadataQuery
UPDATE namespace_metadata SET notification_version = $1 WHERE notification_version = $2 AND partition_id=$3

-- nexus_endpoints.incrementEndpointsTableVersionQry
UPDATE nexus_endpoints_partition_status SET version = $1 WHERE version = $2

-- nexus_endpoints.createEndpointQry
INSERT INTO nexus_endpoints(id, data, data_encoding, version) VALUES ($1, $2, $3, 1)

-- nexus_endpoints.updateEndpointQry
UPDATE nexus_endpoints SET data = $1, data_encoding = $2, version = $3 WHERE id = $4 AND version = $5

-- nexus_endpoints.deleteEndpointQry
DELETE FROM nexus_endpoints WHERE id = $1

-- nexus_endpoints.getEndpointByIdQry
SELECT id, data, data_encoding, version FROM nexus_endpoints WHERE id = $1

-- nexus_endpoints.getEndpointsQry
SELECT id, data, data_encoding, version FROM nexus_endpoints WHERE id > $1 ORDER BY id LIMIT $2

-- queue.templateGetMessageQuery
SELECT message_id, message_payload, message_encoding FROM queue WHERE queue_type = $1 and message_id = $2

-- queue.templateGetMessagesQuery
SELECT message_id, message_payload, message_encoding FROM queue WHERE queue_type = $1 and message_id > $2 and message_id <= $3 ORDER BY message_id ASC LIMIT $4

-- queue.templateDeleteMessageQuery
DELETE FROM queue WHERE queue_type = $1 and message_id = $2

-- queue.templateRangeDeleteMessagesQuery
DELETE FROM queue WHERE queue_type = $1 and message_id > $2 and message_id <= $3

-- queue.templateGetLastMessageIDQuery
SELECT message_id FROM queue WHERE message_id >= (SELECT message_id FROM queue WHERE queue_type=$1 ORDER BY message_id DESC LIMIT 1) FOR UPDATE

-- queue.templateGetQueueMetadataQuery
SELECT data, data_encoding, version from queue_metadata WHERE queue_type = $1

-- queue_v2.templateGetMessagesQueryV2
SELECT message_id, message_payload, message_encoding FROM queue_messages WHERE queue_type = $1 and queue_name = $2 and queue_partition = $3 and message_id >= $4 ORDER BY message_id ASC LIMIT $5

-- queue_v2.templateRangeDeleteMessagesQueryV2
DELETE FROM queue_messages WHERE queue_type = $1 and queue_name = $2 and queue_partition = $3 and message_id >= $4 and message_id <= $5

-- queue_v2.templateGetLastMessageIDQueryV2
SELECT message_id FROM queue_messages WHERE queue_type=$1 and queue_name=$2 and queue_partition=$3 and message_id >= (SELECT message_id FROM queue_messages WHERE queue_type=$1 and queue_name=$2 and queue_partition=$3 ORDER BY message_id DESC LIMIT 1) FOR UPDATE

-- queue_v2.templateGetQueueMetadataQueryV2
SELECT metadata_payload, metadata_encoding from queues WHERE queue_type=$1 and queue_name=$2

-- queue_v2.templateGetQueueMetadataQueryV2ForUpdate
SELECT metadata_payload, metadata_encoding from queues WHERE queue_type=$1 and queue_name=$2 FOR UPDATE

-- queue_v2.templateGetNameFromQueueMetadataV2
SELECT queue_type, queue_name, metadata_payload, metadata_encoding from queues WHERE queue_type=$1 LIMIT $2 OFFSET $3

-- shard.createShardQry
INSERT INTO shards (shard_id, range_id, data, data_encoding) VALUES ($1, $2, $3, $4)

-- shard.getShardQry
SELECT shard_id, range_id, data, data_encoding FROM shards WHERE shard_id = $1

-- shard.updateShardQry
UPDATE shards SET range_id = $1, data = $2, data_encoding = $3 WHERE shard_id = $4

-- shard.lockShardQry
SELECT range_id FROM shards WHERE shard_id = $1 FOR UPDATE

-- shard.readLockShardQry
SELECT range_id FROM shards WHERE shard_id = $1 FOR SHARE

-- task_queues.deleteTaskQueueQry
DELETE FROM task_queues_v2 WHERE range_hash=$1 AND task_queue_id=$2 AND range_id=$3

-- task_queues.lockTaskQueueQry
SELECT range_id FROM task_queues_v2 WHERE range_hash=$1 AND task_queue_id=$2 FOR UPDATE

-- task_user_data.getTaskQueueUserDataQry
SELECT data, data_encoding, version FROM task_queue_user_data WHERE namespace_id = $1 AND task_queue_name = $2

-- task_user_data.updateTaskQueueUserDataQry
UPDATE task_queue_user_data SET data = $1, data_encoding = $2, version = $3 WHERE namespace_id = $4 AND task_queue_name = $5 AND version = $6

-- task_user_data.insertTaskQueueUserDataQry
INSERT INTO task_queue_user_data(namespace_id, task_queue_name, data, data_encoding, version) VALUES ($1, $2, $3, $4, 1)

-- task_user_data.listTaskQueueUserDataQry
SELECT task_queue_name, data, data_encoding, version FROM task_queue_user_data WHERE namespace_id = $1 AND task_queue_name > $2 LIMIT $3

-- task_user_data.removeBuildIdToTaskQueueMappingQry
DELETE FROM build_id_to_task_queue WHERE namespace_id = $1 AND task_queue_name = $2 AND build_id IN (

-- task_user_data.listTaskQueuesByBuildIdQry
SELECT task_queue_name FROM build_id_to_task_queue WHERE namespace_id = $1 AND build_id = $2

-- task_user_data.countTaskQueuesByBuildIdQry
SELECT COUNT(*) FROM build_id_to_task_queue WHERE namespace_id = $1 AND build_id = $2

-- task_v1.getTaskMinMaxQry
SELECT task_id, data, data_encoding FROM tasks WHERE range_hash = $1 AND task_queue_id=$2 AND task_id >= $3 AND task_id < $4 ORDER BY task_id LIMIT $5

-- task_v1.getTaskMinQry
SELECT task_id, data, data_encoding FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id >= $3 ORDER BY task_id LIMIT $4

-- task_v1.rangeDeleteTaskQry
DELETE FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id IN (SELECT task_id FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id < $3 ORDER BY task_queue_id,task_id LIMIT $4 )

-- task_v2.getTaskV2Qry
SELECT task_id, data, data_encoding FROM tasks_v2 WHERE range_hash = $1 AND task_queue_id = $2 AND (pass, task_id) >= ($3, $4) ORDER BY pass, task_id

-- task_v2.rangeDeleteTaskV2Qry
DELETE FROM tasks_v2 WHERE range_hash = $1 AND task_queue_id = $2 AND task_id IN (SELECT task_id FROM tasks_v2 WHERE range_hash = $1 AND task_queue_id = $2 AND (pass, task_id) < ($3, $4) ORDER BY task_queue_id,pass,task_id LIMIT $5 )

