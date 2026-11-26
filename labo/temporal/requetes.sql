DELETE FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id IN (SELECT task_id FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id < $3 ORDER BY task_queue_id, task_id LIMIT $4)

SELECT task_id, data, data_encoding FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id >= $3 AND task_id < $4 ORDER BY task_id LIMIT $5

DELETE FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id = ANY(ARRAY(SELECT task_id FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id < $3 ORDER BY task_queue_id, task_id LIMIT $4))
