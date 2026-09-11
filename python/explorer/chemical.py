import sqlite3
import pandas as pd
from typing import List, Dict, Optional, Tuple
import os

from . import logger


class ChemicalDatabase:
    """化学品数据库（整体结构沿用 ToxicGasDatabase）"""

    # 所有数据列（不含 id 与时间戳），供导入 / 导出 / 更新复用
    FIELDS = [
        '化学品名称', '别名', '分子式', 'CAS号', '分子量',
        '危险性类别', '物理状态', '沸点_C', '熔点_C', '闪点_C',
        '爆炸下限', '爆炸上限', '相对密度', '溶解性', '危险特性',
    ]

    # 需要按数值处理的列
    NUMERIC_FIELDS = [
        '分子量', '沸点_C', '熔点_C', '闪点_C',
        '爆炸下限', '爆炸上限', '相对密度',
    ]

    # 不允许为空的列
    REQUIRED_FIELDS = ['化学品名称', '分子式', 'CAS号', '危险性类别']

    def __init__(self, db_name: str = 'db/chemical.db', excel_path: str = None):
        """
        初始化数据库
        :param db_name: 数据库文件名
        :param excel_path: Excel文件路径（可选）
        """
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.create_table()

        # 如果提供了Excel文件路径，导入数据
        if excel_path and os.path.exists(excel_path):
            self.import_from_excel(excel_path)

    def create_table(self):
        """创建化学品信息表"""
        create_table_sql = '''
        CREATE TABLE IF NOT EXISTS chemicals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            化学品名称 TEXT NOT NULL,
            别名 TEXT,
            分子式 TEXT NOT NULL UNIQUE,
            CAS号 TEXT NOT NULL UNIQUE,
            分子量 REAL,
            危险性类别 TEXT NOT NULL,
            物理状态 TEXT,
            沸点_C REAL,
            熔点_C REAL,
            闪点_C REAL,
            爆炸下限 REAL,
            爆炸上限 REAL,
            相对密度 REAL,
            溶解性 TEXT,
            危险特性 TEXT,
            created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
        self.cursor.execute(create_table_sql)

        # 创建更新时间触发器
        trigger_sql = '''
        CREATE TRIGGER IF NOT EXISTS update_chemical_timestamp 
        AFTER UPDATE ON chemicals
        FOR EACH ROW
        BEGIN
            UPDATE chemicals SET updated_time = CURRENT_TIMESTAMP
            WHERE id = OLD.id;
        END;
        '''
        self.cursor.execute(trigger_sql)
        self.conn.commit()

    @staticmethod
    def _is_blank(value) -> bool:
        """判断单元格是否为空（含 NaN / None）"""
        if value is None:
            return True
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    def _build_record(self, row) -> Dict:
        """把一行 Excel 数据规整为入库字典"""
        record = {field: None for field in self.FIELDS}
        for field in self.FIELDS:
            if field not in row.index:
                continue
            value = row[field]
            if self._is_blank(value):
                continue
            if field in self.NUMERIC_FIELDS:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            else:
                value = str(value).strip()
                if not value:
                    continue
            record[field] = value
        return record

    def import_from_excel(self, excel_path: str):
        """从Excel文件导入数据"""
        try:
            df = pd.read_excel(excel_path)

            # 确保列名与数据库匹配（处理可能的空格或格式差异）
            column_mapping = {
                '化学品名称': '化学品名称',
                '名称': '化学品名称',
                '品名': '化学品名称',
                '别名': '别名',
                '分子式': '分子式',
                'CAS 号': 'CAS号',
                'CAS号': 'CAS号',
                'CAS': 'CAS号',
                '分子量': '分子量',
                '危险性类别': '危险性类别',
                '危险类别': '危险性类别',
                '物理状态': '物理状态',
                '状态': '物理状态',
                '沸点 (℃)': '沸点_C',
                '沸点(℃)': '沸点_C',
                '沸点_C': '沸点_C',
                '沸点': '沸点_C',
                '熔点 (℃)': '熔点_C',
                '熔点(℃)': '熔点_C',
                '熔点_C': '熔点_C',
                '熔点': '熔点_C',
                '闪点 (℃)': '闪点_C',
                '闪点(℃)': '闪点_C',
                '闪点_C': '闪点_C',
                '闪点': '闪点_C',
                '爆炸下限 (%)': '爆炸下限',
                '爆炸下限(%)': '爆炸下限',
                '爆炸下限': '爆炸下限',
                '爆炸上限 (%)': '爆炸上限',
                '爆炸上限(%)': '爆炸上限',
                '爆炸上限': '爆炸上限',
                '相对密度': '相对密度',
                '密度': '相对密度',
                '溶解性': '溶解性',
                '危险特性': '危险特性',
            }

            # 重命名列
            df = df.rename(columns=column_mapping)

            # 插入数据
            imported = 0
            for _, row in df.iterrows():
                if self.add_chemical(self._build_record(row)):
                    imported += 1
            logger.debug(f"成功从 {excel_path} 导入 {imported}/{len(df)} 条数据")
        except Exception as e:
            logger.error(f"导入Excel数据失败: {e}")

    def add_chemical(self, chemical_data: Dict) -> bool:
        """
        添加化学品信息
        :param chemical_data: 化学品数据字典
        :return: 成功返回True，失败返回False
        """
        try:
            missing = [f for f in self.REQUIRED_FIELDS if self._is_blank(
                chemical_data.get(f))]
            if missing:
                logger.error(
                    f"缺少必填字段 {missing}: {chemical_data.get('化学品名称')}")
                return False

            fields = ', '.join(self.FIELDS)
            placeholders = ', '.join(['?'] * len(self.FIELDS))
            sql = f"INSERT INTO chemicals ({fields}) VALUES ({placeholders})"
            values = tuple(chemical_data.get(field) for field in self.FIELDS)

            self.cursor.execute(sql, values)
            self.conn.commit()
            logger.debug(f"成功添加化学品: {chemical_data.get('化学品名称')}")
            return True
        except sqlite3.IntegrityError:
            logger.error(
                f"化学品已存在（分子式或CAS号重复）: {chemical_data.get('化学品名称')}")
            return False
        except Exception as e:
            logger.error(f"添加化学品失败: {e}")
            return False

    def delete_chemical(self, identifier: str, by_cas: bool = False) -> bool:
        """
        删除化学品信息
        :param identifier: 标识符（分子式或CAS号）
        :param by_cas: 是否按CAS号删除，False则按分子式删除
        :return: 成功返回True，失败返回False
        """
        try:
            if by_cas:
                sql = "DELETE FROM chemicals WHERE CAS号 = ?"
            else:
                sql = "DELETE FROM chemicals WHERE 分子式 = ?"

            self.cursor.execute(sql, (identifier,))
            self.conn.commit()

            if self.cursor.rowcount > 0:
                logger.debug(f"成功删除化学品: {identifier}")
                return True
            else:
                logger.debug(f"未找到化学品: {identifier}")
                return False
        except Exception as e:
            logger.error(f"删除化学品失败: {e}")
            return False

    def update_chemical(self, molecular_formula: str, update_data: Dict) -> bool:
        """
        更新化学品信息
        :param molecular_formula: 分子式（作为更新条件）
        :param update_data: 要更新的数据字典
        :return: 成功返回True，失败返回False
        """
        try:
            # 构建更新语句
            set_clauses = []
            values = []

            for key, value in update_data.items():
                if key not in self.FIELDS:
                    continue
                if key in self.NUMERIC_FIELDS:
                    if self._is_blank(value):
                        values.append(None)
                    else:
                        values.append(float(value))
                else:
                    values.append(value)
                set_clauses.append(f"{key} = ?")

            if not set_clauses:
                logger.debug("没有提供可更新的数据")
                return False

            sql = f"UPDATE chemicals SET {', '.join(set_clauses)} WHERE 分子式 = ?"
            values.append(molecular_formula)

            self.cursor.execute(sql, tuple(values))
            self.conn.commit()

            if self.cursor.rowcount > 0:
                logger.debug(f"成功更新化学品: {molecular_formula}")
                return True
            else:
                logger.debug(f"未找到化学品: {molecular_formula}")
                return False
        except Exception as e:
            logger.error(f"更新化学品失败: {e}")
            return False

    def search_chemicals(self,
                         condition: str = None,
                         value: str = None,
                         hazard_class: str = None,
                         physical_state: str = None,
                         min_boiling_point: float = None,
                         max_boiling_point: float = None) -> List[Dict]:
        """
        查询化学品信息
        :param condition: 查询条件字段
        :param value: 查询值
        :param hazard_class: 危险性类别筛选
        :param physical_state: 物理状态筛选
        :param min_boiling_point: 最低沸点
        :param max_boiling_point: 最高沸点
        :return: 查询结果列表
        """
        try:
            sql = "SELECT * FROM chemicals WHERE 1=1"
            params = []

            # 根据条件动态构建查询
            if condition and value:
                if condition == '化学品名称':
                    sql += " AND 化学品名称 LIKE ?"
                    params.append(f"%{value}%")
                elif condition == '别名':
                    sql += " AND 别名 LIKE ?"
                    params.append(f"%{value}%")
                elif condition == '分子式':
                    sql += " AND 分子式 = ?"
                    params.append(value)
                elif condition == 'CAS号':
                    sql += " AND CAS号 = ?"
                    params.append(value)
                elif condition == '危险性类别':
                    sql += " AND 危险性类别 = ?"
                    params.append(value)

            if hazard_class:
                sql += " AND 危险性类别 = ?"
                params.append(hazard_class)

            if physical_state:
                sql += " AND 物理状态 = ?"
                params.append(physical_state)

            if min_boiling_point is not None:
                sql += " AND 沸点_C >= ?"
                params.append(min_boiling_point)

            if max_boiling_point is not None:
                sql += " AND 沸点_C <= ?"
                params.append(max_boiling_point)

            sql += " ORDER BY 危险性类别, 化学品名称"

            self.cursor.execute(sql, tuple(params))
            results = self.cursor.fetchall()

            # 获取列名
            column_names = [description[0]
                            for description in self.cursor.description]

            # 转换为字典列表
            chemicals = []
            for row in results:
                chemical_dict = dict(zip(column_names, row))
                chemicals.append(chemical_dict)

            logger.debug(f"找到 {len(chemicals)} 条记录")
            return chemicals
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []

    def get_all_chemicals(self) -> List[Dict]:
        """获取所有化学品信息"""
        return self.search_chemicals()

    def get_chemical_by_molecular_formula(self, molecular_formula: str) -> Optional[Dict]:
        """根据分子式获取化学品信息"""
        results = self.search_chemicals(condition='分子式', value=molecular_formula)
        return results[0] if results else None

    def get_chemicals_by_hazard(self, hazard_class: str) -> List[Dict]:
        """根据危险性类别获取化学品信息"""
        return self.search_chemicals(hazard_class=hazard_class)

    def get_hazard_classes(self) -> List[str]:
        """获取所有已存在的危险性类别（供筛选项使用）"""
        try:
            self.cursor.execute(
                "SELECT DISTINCT 危险性类别 FROM chemicals WHERE 危险性类别 IS NOT NULL ORDER BY 危险性类别")
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取危险性类别失败: {e}")
            return []

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        try:
            stats = {}

            # 总记录数
            self.cursor.execute("SELECT COUNT(*) FROM chemicals")
            stats['total_chemicals'] = self.cursor.fetchone()[0]

            # 按危险性类别统计
            self.cursor.execute(
                "SELECT 危险性类别, COUNT(*) FROM chemicals GROUP BY 危险性类别")
            stats['hazard_distribution'] = dict(self.cursor.fetchall())

            # 按物理状态统计
            self.cursor.execute(
                "SELECT 物理状态, COUNT(*) FROM chemicals WHERE 物理状态 IS NOT NULL GROUP BY 物理状态")
            stats['state_distribution'] = dict(self.cursor.fetchall())

            # 平均分子量
            self.cursor.execute("SELECT AVG(分子量) FROM chemicals")
            stats['avg_molecular_weight'] = self.cursor.fetchone()[0]

            # 沸点范围
            self.cursor.execute("SELECT MIN(沸点_C), MAX(沸点_C) FROM chemicals")
            min_boil, max_boil = self.cursor.fetchone()
            if min_boil is not None and max_boil is not None:
                stats['boiling_point_range'] = f"{min_boil}℃ 到 {max_boil}℃"
            else:
                stats['boiling_point_range'] = 'N/A'

            # 闪点范围
            self.cursor.execute("SELECT MIN(闪点_C), MAX(闪点_C) FROM chemicals")
            min_flash, max_flash = self.cursor.fetchone()
            if min_flash is not None and max_flash is not None:
                stats['flash_point_range'] = f"{min_flash}℃ 到 {max_flash}℃"
            else:
                stats['flash_point_range'] = 'N/A'

            return stats
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}

    def export_to_excel(self, file_path: str):
        """导出数据到Excel"""
        try:
            chemicals = self.get_all_chemicals()
            if chemicals:
                df = pd.DataFrame(chemicals)
                # 删除不需要的列
                df = df.drop(['id', 'created_time', 'updated_time'],
                             axis=1, errors='ignore')
                # 重命名列以匹配原始格式
                df = df.rename(columns={
                    '沸点_C': '沸点 (℃)',
                    '熔点_C': '熔点 (℃)',
                    '闪点_C': '闪点 (℃)',
                    'CAS号': 'CAS 号',
                    '爆炸下限': '爆炸下限 (%)',
                    '爆炸上限': '爆炸上限 (%)',
                })
                df.to_excel(file_path, index=False)
                logger.debug(f"数据已导出到: {file_path}")
        except Exception as e:
            logger.debug(f"导出失败: {e}")

    def close(self):
        """关闭数据库连接"""
        self.conn.close()
        logger.debug("数据库连接已关闭")
