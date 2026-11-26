from plancliff.parameters import Column, parameter_columns


def test_an_equality_binds_the_parameter_to_its_column():
    assert parameter_columns("select id from jobs where status = $1") == {1: Column("jobs", "status")}


def test_the_parameter_may_stand_on_the_left_of_the_comparison():
    assert parameter_columns("select id from jobs where $1 = status") == {1: Column("jobs", "status")}


def test_an_alias_resolves_to_the_real_table_and_schema():
    query = "select o.id from app.orders o join app.clients c on c.id = o.client_id where c.segment = $1 and o.state = $2"
    assert parameter_columns(query) == {1: Column("clients", "segment", "app"), 2: Column("orders", "state", "app")}


def test_each_member_of_an_in_list_is_bound_to_the_column():
    assert parameter_columns("select 1 from t where kind in ($1, $2)") == {1: Column("t", "kind"), 2: Column("t", "kind")}


def test_row_tuples_bind_position_by_position():
    query = "select 1 from tuple where (object_type, relation) in (($1, $2), ($3, $4))"
    assert parameter_columns(query) == {
        1: Column("tuple", "object_type"), 2: Column("tuple", "relation"),
        3: Column("tuple", "object_type"), 4: Column("tuple", "relation"),
    }


def test_insert_values_and_update_set_bind_to_their_target_columns():
    assert parameter_columns("insert into jobs (status, payload) values ($1, $2)") == {1: Column("jobs", "status"), 2: Column("jobs", "payload")}
    assert parameter_columns("update jobs set status = $1 where id = $2") == {1: Column("jobs", "status"), 2: Column("jobs", "id")}


def test_a_parameter_used_twice_keeps_its_first_column():
    query = "delete from tasks where queue = $1 and id in (select id from tasks where queue = $1 and id < $2)"
    assert parameter_columns(query) == {1: Column("tasks", "queue"), 2: Column("tasks", "id")}


def test_a_limit_parameter_has_no_column():
    assert parameter_columns("select id from jobs where status = $1 limit $2") == {1: Column("jobs", "status")}


def test_an_unqualified_column_in_a_join_is_left_out_rather_than_guessed():
    assert parameter_columns("select 1 from a join b on a.id = b.a_id where label = $1") == {}


def test_a_cte_name_is_not_a_table_so_its_columns_stay_resolvable():
    query = "with q as (select id from jobs where status = $1 order by created_at limit $2) delete from jobs where id in (select id from q)"
    assert parameter_columns(query) == {1: Column("jobs", "status")}


def test_a_column_qualified_by_a_cte_name_is_left_out():
    assert parameter_columns("with q as (select id, status from jobs) select id from q where q.status = $1") == {}
