import sqlite3
import pandas as pd
from typing import List, Dict, Optional, Tuple
import os

from . import logger


class ToxicGasDatabase:
    def __init__(self, db_name: str = 'db/toxic_gases.db', excel_path: str = None):
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
        """创建气体信息表"""
        create_table_sql = '''
        CREATE TABLE IF NOT EXISTS toxic_gases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            气体名称 TEXT NOT NULL,
            分子式 TEXT NOT NULL UNIQUE,
            CAS号 TEXT NOT NULL UNIQUE,
            分子量 REAL NOT NULL,
            毒性等级 TEXT NOT NULL,
            沸点_C REAL NOT NULL,
            熔点_C REAL NOT NULL,
            IDLH浓度 TEXT NOT NULL,
            MAC浓度 TEXT NOT NULL,
            安全阈值 TEXT NOT NULL,
            警戒浓度 TEXT NOT NULL,
            危险浓度 TEXT NOT NULL,
            created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
        self.cursor.execute(create_table_sql)

        # 创建更新时间触发器
        trigger_sql = '''
        CREATE TRIGGER IF NOT EXISTS update_gas_timestamp 
        AFTER UPDATE ON toxic_gases
        FOR EACH ROW
        BEGIN
            UPDATE toxic_gases SET updated_time = CURRENT_TIMESTAMP
            WHERE id = OLD.id;
        END;
        '''
        self.cursor.execute(trigger_sql)
        self.conn.commit()

    def import_from_excel(self, excel_path: str):
        """从Excel文件导入数据"""
        try:
            df = pd.read_excel(excel_path)

            # 确保列名与数据库匹配（处理可能的空格或格式差异）
            column_mapping = {
                '气体名称': '气体名称',
                '分子式': '分子式',
                'CAS 号': 'CAS号',
                'CAS号': 'CAS号',
                '分子量': '分子量',
                '毒性等级': '毒性等级',
                '沸点 (℃)': '沸点_C',
                '沸点_C': '沸点_C',
                '熔点 (℃)': '熔点_C',
                '熔点_C': '熔点_C',
                'IDLH 浓度': 'IDLH浓度',
                'IDLH浓度': 'IDLH浓度',
                'MAC 浓度': 'MAC浓度',
                'MAC浓度': 'MAC浓度',
                '安全阈值': '安全阈值',
                '警戒浓度': '警戒浓度',
                '危险浓度': '危险浓度'
            }

            # 重命名列
            df = df.rename(columns=column_mapping)

            # 插入数据
            for _, row in df.iterrows():
                self.add_gas({
                    '气体名称': row['气体名称'],
                    '分子式': row['分子式'],
                    'CAS号': str(row['CAS号']).split(' ')[0],
                    '分子量': float(row['分子量']),
                    '毒性等级': row['毒性等级'],
                    '沸点_C': float(row['沸点_C']),
                    '熔点_C': float(row['熔点_C']),
                    'IDLH浓度': str(row['IDLH浓度']),
                    'MAC浓度': str(row['MAC浓度']),
                    '安全阈值': str(row['安全阈值']),
                    '警戒浓度': str(row['警戒浓度']),
                    '危险浓度': str(row['危险浓度'])
                })
            logger.debug(f"成功从 {excel_path} 导入 {len(df)} 条数据")
        except Exception as e:
            logger.error(f"导入Excel数据失败: {e}")

    def add_gas(self, gas_data: Dict) -> bool:
        """
        添加气体信息
        :param gas_data: 气体数据字典
        :return: 成功返回True，失败返回False
        """
        try:
            sql = '''
            INSERT INTO toxic_gases 
            (气体名称, 分子式, CAS号, 分子量, 毒性等级, 沸点_C, 熔点_C, IDLH浓度, MAC浓度, 安全阈值, 警戒浓度, 危险浓度)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            values = (
                gas_data['气体名称'],
                gas_data['分子式'],
                gas_data['CAS号'],
                gas_data['分子量'],
                gas_data['毒性等级'],
                gas_data['沸点_C'],
                gas_data['熔点_C'],
                gas_data['IDLH浓度'],
                gas_data['MAC浓度'],
                gas_data['安全阈值'],
                gas_data['警戒浓度'],
                gas_data['危险浓度']
            )
            self.cursor.execute(sql, values)
            self.conn.commit()
            logger.debug(f"成功添加气体: {gas_data['气体名称']}")
            return True
        except sqlite3.IntegrityError:
            logger.error(f"气体已存在（分子式或CAS号重复）: {gas_data['气体名称']}")
            return False
        except Exception as e:
            logger.error(f"添加气体失败: {e}")
            return False

    def delete_gas(self, identifier: str, by_cas: bool = False) -> bool:
        """
        删除气体信息
        :param identifier: 标识符（分子式或CAS号）
        :param by_cas: 是否按CAS号删除，False则按分子式删除
        :return: 成功返回True，失败返回False
        """
        try:
            if by_cas:
                sql = "DELETE FROM toxic_gases WHERE CAS号 = ?"
            else:
                sql = "DELETE FROM toxic_gases WHERE 分子式 = ?"

            self.cursor.execute(sql, (identifier,))
            self.conn.commit()

            if self.cursor.rowcount > 0:
                logger.debug(f"成功删除气体: {identifier}")
                return True
            else:
                logger.debug(f"未找到气体: {identifier}")
                return False
        except Exception as e:
            logger.error(f"删除气体失败: {e}")
            return False

    def update_gas(self, molecular_formula: str, update_data: Dict) -> bool:
        """
        更新气体信息
        :param molecular_formula: 分子式（作为更新条件）
        :param update_data: 要更新的数据字典
        :return: 成功返回True，失败返回False
        """
        try:
            # 构建更新语句
            set_clauses = []
            values = []

            for key, value in update_data.items():
                if key in ['气体名称', '分子式', 'CAS号', '毒性等级', 'IDLH浓度', 'MAC浓度']:
                    set_clauses.append(f"{key} = ?")
                    values.append(value)
                elif key in ['分子量', '沸点_C', '熔点_C']:
                    set_clauses.append(f"{key} = ?")
                    values.append(float(value))

            if not set_clauses:
                logger.debug("没有提供可更新的数据")
                return False

            sql = f"UPDATE toxic_gases SET {', '.join(set_clauses)} WHERE 分子式 = ?"
            values.append(molecular_formula)

            self.cursor.execute(sql, tuple(values))
            self.conn.commit()

            if self.cursor.rowcount > 0:
                logger.debug(f"成功更新气体: {molecular_formula}")
                return True
            else:
                logger.debug(f"未找到气体: {molecular_formula}")
                return False
        except Exception as e:
            logger.error(f"更新气体失败: {e}")
            return False

    def search_gases(self,
                     condition: str = None,
                     value: str = None,
                     toxicity_level: str = None,
                     min_boiling_point: float = None,
                     max_boiling_point: float = None) -> List[Dict]:
        """
        查询气体信息
        :param condition: 查询条件字段
        :param value: 查询值
        :param toxicity_level: 毒性等级筛选
        :param min_boiling_point: 最低沸点
        :param max_boiling_point: 最高沸点
        :return: 查询结果列表
        """
        try:
            sql = "SELECT * FROM toxic_gases WHERE 1=1"
            params = []

            # 根据条件动态构建查询
            if condition and value:
                if condition == '气体名称':
                    sql += " AND 气体名称 LIKE ?"
                    params.append(f"%{value}%")
                elif condition == '分子式':
                    sql += " AND 分子式 = ?"
                    params.append(value)
                elif condition == 'CAS号':
                    sql += " AND CAS号 = ?"
                    params.append(value)
                elif condition == '毒性等级':
                    sql += " AND 毒性等级 = ?"
                    params.append(value)

            if toxicity_level:
                sql += " AND 毒性等级 = ?"
                params.append(toxicity_level)

            if min_boiling_point is not None:
                sql += " AND 沸点_C >= ?"
                params.append(min_boiling_point)

            if max_boiling_point is not None:
                sql += " AND 沸点_C <= ?"
                params.append(max_boiling_point)

            sql += " ORDER BY 毒性等级, 气体名称"

            self.cursor.execute(sql, tuple(params))
            results = self.cursor.fetchall()

            # 获取列名
            column_names = [description[0]
                            for description in self.cursor.description]

            # 转换为字典列表
            gases = []
            for row in results:
                gas_dict = dict(zip(column_names, row))
                gases.append(gas_dict)

            logger.debug(f"找到 {len(gases)} 条记录")
            return gases
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []

    def get_all_gases(self) -> List[Dict]:
        """获取所有气体信息"""
        return self.search_gases()

    def get_gas_by_molecular_formula(self, molecular_formula: str) -> Optional[Dict]:
        """根据分子式获取气体信息"""
        results = self.search_gases(condition='分子式', value=molecular_formula)
        return results[0] if results else None

    def get_gases_by_toxicity(self, toxicity_level: str) -> List[Dict]:
        """根据毒性等级获取气体信息"""
        return self.search_gases(toxicity_level=toxicity_level)

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        try:
            stats = {}

            # 总记录数
            self.cursor.execute("SELECT COUNT(*) FROM toxic_gases")
            stats['total_gases'] = self.cursor.fetchone()[0]

            # 按毒性等级统计
            self.cursor.execute(
                "SELECT 毒性等级, COUNT(*) FROM toxic_gases GROUP BY 毒性等级")
            stats['toxicity_distribution'] = dict(self.cursor.fetchall())

            # 平均分子量
            self.cursor.execute("SELECT AVG(分子量) FROM toxic_gases")
            stats['avg_molecular_weight'] = self.cursor.fetchone()[0]

            # 沸点范围
            self.cursor.execute("SELECT MIN(沸点_C), MAX(沸点_C) FROM toxic_gases")
            min_boil, max_boil = self.cursor.fetchone()
            stats['boiling_point_range'] = f"{min_boil}℃ 到 {max_boil}℃"

            return stats
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}

    def export_to_excel(self, file_path: str):
        """导出数据到Excel"""
        try:
            gases = self.get_all_gases()
            if gases:
                df = pd.DataFrame(gases)
                # 删除不需要的列
                df = df.drop(['id', 'created_time', 'updated_time'],
                             axis=1, errors='ignore')
                # 重命名列以匹配原始格式
                df = df.rename(columns={
                    '沸点_C': '沸点 (℃)',
                    '熔点_C': '熔点 (℃)',
                    'CAS号': 'CAS 号',
                    'IDLH浓度': 'IDLH 浓度',
                    'MAC浓度': 'MAC 浓度'
                })
                df.to_excel(file_path, index=False)
                logger.debug(f"数据已导出到: {file_path}")
        except Exception as e:
            logger.debug(f"导出失败: {e}")

    def close(self):
        """关闭数据库连接"""
        self.conn.close()
        logger.debug("数据库连接已关闭")
