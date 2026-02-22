"""
Data Source Abstraction Layer
Supports loading data from Excel, SQLite, and Snowflake while maintaining consistent DataFrame structure
"""
import pandas as pd
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

class DataSource:
    """Abstract data source that returns consistent DataFrame structure"""

    @staticmethod
    def load_from_excel(file_path: str) -> pd.DataFrame:
        """
        Load data from Excel or CSV file

        Args:
            file_path: Path to Excel or CSV file

        Returns:
            DataFrame with canvas_dec_matches data
        """
        file_path = Path(file_path)
        if not file_path.exists():
            print(f"Warning: File not found: {file_path}")
            return pd.DataFrame()

        if file_path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
        return DataSource._normalize_dataframe(df)

    @staticmethod
    def load_from_sqlite(db_path: str, table_name: str) -> pd.DataFrame:
        """
        Load data from SQLite database

        Args:
            db_path: Path to SQLite database file
            table_name: Name of table to query

        Returns:
            DataFrame with canvas_dec_matches data
        """
        db_path = Path(db_path)
        if not db_path.exists():
            print(f"Warning: SQLite database not found: {db_path}")
            return pd.DataFrame()

        conn = sqlite3.connect(db_path)
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            return DataSource._normalize_dataframe(df)
        except Exception as e:
            print(f"Error loading from SQLite: {e}")
            return pd.DataFrame()
        finally:
            conn.close()

    @staticmethod
    def load_from_snowflake(
        account: str,
        user: str,
        password: str,
        database: str,
        schema: str,
        table: str,
        warehouse: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Load data from Snowflake

        Args:
            account: Snowflake account identifier
            user: Username
            password: Password
            database: Database name
            schema: Schema name
            table: Table name
            warehouse: Optional warehouse name

        Returns:
            DataFrame with canvas_dec_matches data
        """
        try:
            from snowflake import connector
        except ImportError:
            print("Error: snowflake-connector-python not installed")
            print("Install with: pip install snowflake-connector-python")
            return pd.DataFrame()

        try:
            conn_params = {
                'account': account,
                'user': user,
                'password': password,
                'database': database,
                'schema': schema
            }
            if warehouse:
                conn_params['warehouse'] = warehouse

            conn = connector.connect(**conn_params)
            try:
                df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
                return DataSource._normalize_dataframe(df)
            finally:
                conn.close()
        except Exception as e:
            print(f"Error loading from Snowflake: {e}")
            return pd.DataFrame()

    @staticmethod
    def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure consistent column names, data types, and required columns.
        Handles column mapping for tables with different schemas (e.g. dec_ba_master).

        Args:
            df: Raw DataFrame from any source

        Returns:
            Normalized DataFrame with consistent structure
        """
        # Detect dec_ba_master schema and map columns to expected grid structure
        if 'hdrcode' in df.columns and 'canvas_id' not in df.columns:
            column_map = {
                'hdrcode': 'dec_hdrcode',
                'ssn': 'canvas_ssn',
                'hdrname': 'dec_name',
                'addrcontact': 'dec_contact',
                'addraddress': 'dec_address',
                'addrcity': 'dec_city',
                'addrstate': 'dec_state',
                'addrzipcode': 'dec_zip',
                'addrsubcode': 'dec_addrsubcode',
            }
            df = df.rename(columns=column_map)

            # Add missing canvas columns with empty values
            for col in ('canvas_id', 'canvas_name', 'canvas_address',
                        'canvas_city', 'canvas_state', 'canvas_zip'):
                if col not in df.columns:
                    df[col] = ''

            # Add missing score/recommendation columns with defaults
            if 'ssn_match' not in df.columns:
                df['ssn_match'] = 0
            if 'name_score' not in df.columns:
                df['name_score'] = 0
            if 'address_score' not in df.columns:
                df['address_score'] = 0
            if 'recommendation' not in df.columns:
                df['recommendation'] = ''
            if 'address_reason' not in df.columns:
                df['address_reason'] = ''

        # Ensure jib, rev, vendor columns exist (defaulting to 0)
        for col in ('jib', 'rev', 'vendor'):
            if col not in df.columns:
                df[col] = 0

        # Convert boolean columns to int if needed
        for col in ('jib', 'rev', 'vendor'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

        # Ensure numeric columns are properly typed
        numeric_cols = ['ssn_match', 'name_score', 'address_score']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    @staticmethod
    def save_to_excel(df: pd.DataFrame, file_path: str) -> None:
        """
        Save DataFrame to Excel file

        Args:
            df: DataFrame to save
            file_path: Path to Excel file
        """
        df.to_excel(file_path, index=False)

    @staticmethod
    def save_to_sqlite(df: pd.DataFrame, db_path: str, table_name: str, if_exists: str = 'replace') -> None:
        """
        Save DataFrame to SQLite database

        Args:
            df: DataFrame to save
            db_path: Path to SQLite database file
            table_name: Name of table to create/update
            if_exists: How to behave if table exists ('fail', 'replace', 'append')
        """
        conn = sqlite3.connect(db_path)
        try:
            df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        finally:
            conn.close()

    @staticmethod
    def save_to_snowflake(
        df: pd.DataFrame,
        account: str,
        user: str,
        password: str,
        database: str,
        schema: str,
        table: str,
        warehouse: Optional[str] = None,
        if_exists: str = 'replace'
    ) -> None:
        """
        Save DataFrame to Snowflake

        Args:
            df: DataFrame to save
            account: Snowflake account identifier
            user: Username
            password: Password
            database: Database name
            schema: Schema name
            table: Table name
            warehouse: Optional warehouse name
            if_exists: How to behave if table exists ('fail', 'replace', 'append')
        """
        try:
            from snowflake import connector
            from snowflake.connector.pandas_tools import write_pandas
        except ImportError:
            print("Error: snowflake-connector-python not installed")
            return

        conn_params = {
            'account': account,
            'user': user,
            'password': password,
            'database': database,
            'schema': schema
        }
        if warehouse:
            conn_params['warehouse'] = warehouse

        conn = connector.connect(**conn_params)
        try:
            success, nchunks, nrows, _ = write_pandas(
                conn, df, table.upper(), auto_create_table=True, overwrite=(if_exists == 'replace')
            )
            if success:
                print(f"Successfully wrote {nrows} rows to Snowflake")
        finally:
            conn.close()


def load_data(config: Dict[str, Any]) -> pd.DataFrame:
    """
    Load data based on configuration settings

    Args:
        config: Dictionary containing data source configuration

    Returns:
        DataFrame with canvas_dec_matches data

    Example config formats:
        Excel: {'source_type': 'excel', 'file_path': 'path/to/file.xlsx'}
        SQLite: {'source_type': 'sqlite', 'db_path': 'path/to/db.db', 'table_name': 'table_name'}
        Snowflake: {'source_type': 'snowflake', 'account': '...', 'user': '...', 'password': '...',
                    'database': '...', 'schema': '...', 'table': '...'}
    """
    source_type = config.get('source_type', 'excel').lower()

    if source_type == 'excel':
        return DataSource.load_from_excel(config['file_path'])

    elif source_type == 'sqlite':
        return DataSource.load_from_sqlite(
            config['db_path'],
            config['table_name']
        )

    elif source_type == 'snowflake':
        return DataSource.load_from_snowflake(
            account=config['account'],
            user=config['user'],
            password=config['password'],
            database=config['database'],
            schema=config['schema'],
            table=config['table'],
            warehouse=config.get('warehouse')
        )

    else:
        raise ValueError(f"Unknown source type: {source_type}. Supported: 'excel', 'sqlite', 'snowflake'")


def save_data(df: pd.DataFrame, config: Dict[str, Any]) -> None:
    """
    Save data based on configuration settings

    Args:
        df: DataFrame to save
        config: Dictionary containing data source configuration (same format as load_data)
    """
    source_type = config.get('source_type', 'excel').lower()

    if source_type == 'excel':
        DataSource.save_to_excel(df, config['file_path'])

    elif source_type == 'sqlite':
        DataSource.save_to_sqlite(
            df,
            config['db_path'],
            config['table_name'],
            if_exists=config.get('if_exists', 'replace')
        )

    elif source_type == 'snowflake':
        DataSource.save_to_snowflake(
            df,
            account=config['account'],
            user=config['user'],
            password=config['password'],
            database=config['database'],
            schema=config['schema'],
            table=config['table'],
            warehouse=config.get('warehouse'),
            if_exists=config.get('if_exists', 'replace')
        )

    else:
        raise ValueError(f"Unknown source type: {source_type}")
