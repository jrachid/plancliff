SELECT store, object_type, object_id, relation, _user, user_type, condition_name, condition_context, ulid, inserted_at FROM tuple WHERE store = $1 AND (object_type, object_id, relation, _user, user_type) IN (($2, $3, $4, $5, $6), ($7, $8, $9, $10, $11), ($12, $13, $14, $15, $16), ($17, $18, $19, $20, $21), ($22, $23, $24, $25, $26), ($27, $28, $29, $30, $31)) FOR UPDATE

SELECT store, object_type, object_id, relation, _user FROM tuple WHERE store = $1 AND object_type = $2 AND object_id = $3 AND relation = $4
