import pytest

from app.services.sql_tools import execute_readonly_sql, validate_readonly_sql


class TestValidateReadonlySql:
    def test_normal_select_passes(self):
        validate_readonly_sql("SELECT * FROM products")

    def test_select_with_join_passes(self):
        validate_readonly_sql(
            "SELECT p.name, COUNT(r.id) FROM orders o "
            "JOIN products p ON o.product_id = p.id "
            "LEFT JOIN refunds r ON r.order_id = o.id "
            "GROUP BY p.name"
        )

    def test_select_with_group_by_passes(self):
        validate_readonly_sql(
            "SELECT category, COUNT(*) FROM products GROUP BY category"
        )

    def test_select_with_where_passes(self):
        validate_readonly_sql(
            "SELECT * FROM orders WHERE month = '2026-04'"
        )

    def test_select_with_semicolon_passes(self):
        validate_readonly_sql("SELECT * FROM products;")

    def test_drop_is_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("DROP TABLE products")

    def test_delete_is_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("DELETE FROM products WHERE id = 1")

    def test_update_is_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("UPDATE products SET price = 99 WHERE id = 1")

    def test_insert_is_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("INSERT INTO products VALUES (7, 'test', '服装', 100)")

    def test_alter_is_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("ALTER TABLE products ADD COLUMN test TEXT")

    def test_truncate_is_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("TRUNCATE TABLE products")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("")

    def test_non_select_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("DESCRIBE products")

    def test_dangerous_keyword_hidden_in_select_is_rejected(self):
        with pytest.raises(ValueError):
            validate_readonly_sql("SELECT * FROM products; DROP TABLE products")


class TestExecuteReadonlySql:
    def test_normal_sql_returns_sql_result(self):
        result = execute_readonly_sql("SELECT * FROM products")
        assert result.sql == "SELECT * FROM products"
        assert result.error is None
        assert len(result.columns) > 0
        assert len(result.rows) > 0
        assert result.row_count > 0

    def test_syntax_error_returns_error_field(self):
        result = execute_readonly_sql("SELECT * FROM")
        assert result.error is not None
        assert len(result.error) > 0
        assert result.columns == []
        assert result.rows == []
        assert result.row_count == 0

    def test_nonexistent_table_returns_error_field(self):
        result = execute_readonly_sql("SELECT * FROM nonexistent_table_xyz")
        assert result.error is not None
        assert len(result.error) > 0
        assert result.columns == []
        assert result.rows == []
        assert result.row_count == 0
