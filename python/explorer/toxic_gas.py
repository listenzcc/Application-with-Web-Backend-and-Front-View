import sqlite3
import re

import pandas as pd
from typing import List, Dict, Optional, Tuple
import os

from . import logger


class ToxicGasDatabase:
    """有毒气体数据库（2026-09-11 按甲方新表 data/gas/气体库.xlsx 调整）

    相对旧版的变化：
    - 分子式不再唯一（乙醛/环氧乙烷等同分子式不同气体），唯一约束移到 CAS号；
      删除 / 更新一律以 CAS号 为准
    - 沸点 / 熔点改存文本原样（如 "升华 -63.8"、"137至144"、"/"），
      数值统计与沸点范围查询时解析其中的首个数字，解析失败则跳过
    - 新增 LC50 列（LC50(体积分数)/10^-6），无数据以 "/" 表示
    - 毒性等级为自由组合文本（如 "高毒/致癌"），筛选项从库内动态获取
    """

    # 所有数据列（不含 id 与时间戳）
    FIELDS = [
        '气体名称', '分子式', 'CAS号', '分子量', '毒性等级',
        '沸点', '熔点', 'IDLH浓度', 'MAC浓度',
        '安全阈值', '警戒浓度', '危险浓度', 'LC50',
    ]

    # 需要按数值处理的列
    NUMERIC_FIELDS = ['分子量']

    # 文本数值列（内容形如 "升华 -63.8"，统计/筛选时解析首个数字）
    TEXT_NUMERIC_FIELDS = ['沸点', '熔点']

    # 不允许为空的列
    REQUIRED_FIELDS = ['气体名称', '分子式', 'CAS号', '毒性等级']

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
            分子式 TEXT NOT NULL,
            CAS号 TEXT NOT NULL UNIQUE,
            分子量 REAL,
            毒性等级 TEXT NOT NULL,
            沸点 TEXT,
            熔点 TEXT,
            IDLH浓度 TEXT,
            MAC浓度 TEXT,
            安全阈值 TEXT,
            警戒浓度 TEXT,
            危险浓度 TEXT,
            LC50 TEXT,
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

    @staticmethod
    def _is_blank(value) -> bool:
        """判断单元格是否为空（含 NaN / None / '/'）"""
        if value is None:
            return True
        try:
            if bool(pd.isna(value)):
                return True
        except (TypeError, ValueError):
            pass
        return str(value).strip() in ('', '/')

    @staticmethod
    def _parse_number(text) -> Optional[float]:
        """从文本中解析首个数字（如 "升华 -63.8" -> -63.8）"""
        if ToxicGasDatabase._is_blank(text):
            return None
        match = re.search(r'[-+]?\d*\.?\d+', str(text))
        return float(match.group()) if match else None

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
                '气体名称': '气体名称',
                '分子式': '分子式',
                'CAS 号': 'CAS号',
                'CAS号': 'CAS号',
                '分子量': '分子量',
                '毒性等级': '毒性等级',
                '沸点 (℃)': '沸点',
                '沸点(℃)': '沸点',
                '沸点(°C)': '沸点',
                '沸点': '沸点',
                '熔点 (℃)': '熔点',
                '熔点(℃)': '熔点',
                '熔点(°C)': '熔点',
                '熔点': '熔点',
                'IDLH 浓度': 'IDLH浓度',
                'IDLH浓度': 'IDLH浓度',
                'MAC 浓度': 'MAC浓度',
                'MAC浓度': 'MAC浓度',
                '安全阈值': '安全阈值',
                '警戒浓度': '警戒浓度',
                '危险浓度': '危险浓度',
                'LC50(体积分数)/10^-6': 'LC50',
                'LC50(体积分数)/10-6': 'LC50',
                'LC50': 'LC50',
            }

            # 重命名列
            df = df.rename(columns=column_mapping)

            # 插入数据
            imported = 0
            for _, row in df.iterrows():
                if self.add_gas(self._build_record(row)):
                    imported += 1
            logger.debug(f"成功从 {excel_path} 导入 {imported}/{len(df)} 条数据")
        except Exception as e:
            logger.error(f"导入Excel数据失败: {e}")

    def add_gas(self, gas_data: Dict) -> bool:
        """
        添加气体信息
        :param gas_data: 气体数据字典
        :return: 成功返回True，失败返回False
        """
        try:
            missing = [f for f in self.REQUIRED_FIELDS if self._is_blank(
                gas_data.get(f))]
            if missing:
                logger.error(f"缺少必填字段 {missing}: {gas_data.get('气体名称')}")
                return False

            fields = ', '.join(self.FIELDS)
            placeholders = ', '.join(['?'] * len(self.FIELDS))
            sql = f"INSERT INTO toxic_gases ({fields}) VALUES ({placeholders})"
            values = tuple(gas_data.get(field) for field in self.FIELDS)

            self.cursor.execute(sql, values)
            self.conn.commit()
            logger.debug(f"成功添加气体: {gas_data.get('气体名称')}")
            return True
        except sqlite3.IntegrityError:
            logger.error(f"气体已存在（CAS号重复）: {gas_data.get('气体名称')}")
            return False
        except Exception as e:
            logger.error(f"添加气体失败: {e}")
            return False

    def delete_gas(self, cas_no: str, by_cas: bool = True) -> bool:
        """
        删除气体信息
        :param cas_no: 标识符（默认CAS号；by_cas=False时按分子式删除，可能删除多条同分子式气体）
        :param by_cas: 是否按CAS号删除
        :return: 成功返回True，失败返回False
        """
        try:
            if by_cas:
                sql = "DELETE FROM toxic_gases WHERE CAS号 = ?"
            else:
                sql = "DELETE FROM toxic_gases WHERE 分子式 = ?"

            self.cursor.execute(sql, (cas_no,))
            self.conn.commit()

            if self.cursor.rowcount > 0:
                logger.debug(f"成功删除气体: {cas_no}")
                return True
            else:
                logger.debug(f"未找到气体: {cas_no}")
                return False
        except Exception as e:
            logger.error(f"删除气体失败: {e}")
            return False

    def update_gas(self, cas_no: str, update_data: Dict) -> bool:
        """
        更新气体信息（以CAS号作为更新条件）
        :param cas_no: CAS号
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

            sql = f"UPDATE toxic_gases SET {', '.join(set_clauses)} WHERE CAS号 = ?"
            values.append(cas_no)

            self.cursor.execute(sql, tuple(values))
            self.conn.commit()

            if self.cursor.rowcount > 0:
                logger.debug(f"成功更新气体: {cas_no}")
                return True
            else:
                logger.debug(f"未找到气体: {cas_no}")
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
        :param toxicity_level: 毒性等级筛选（模糊匹配，'高毒' 可命中 '高毒/致癌'）
        :param min_boiling_point: 最低沸点（对沸点文本中解析出的数值过滤）
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
                    sql += " AND 毒性等级 LIKE ?"
                    params.append(f"%{value}%")

            if toxicity_level:
                sql += " AND 毒性等级 LIKE ?"
                params.append(f"%{toxicity_level}%")

            sql += " ORDER BY 气体名称"

            self.cursor.execute(sql, tuple(params))
            results = self.cursor.fetchall()

            # 获取列名
            column_names = [description[0]
                            for description in self.cursor.description]

            # 转换为字典列表
            gases = [dict(zip(column_names, row)) for row in results]

            # 沸点为文本，数值范围过滤在应用层完成
            if min_boiling_point is not None:
                gases = [g for g in gases
                         if (v := self._parse_number(g.get('沸点'))) is not None
                         and v >= min_boiling_point]
            if max_boiling_point is not None:
                gases = [g for g in gases
                         if (v := self._parse_number(g.get('沸点'))) is not None
                         and v <= max_boiling_point]

            logger.debug(f"找到 {len(gases)} 条记录")
            return gases
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []

    def get_all_gases(self) -> List[Dict]:
        """获取所有气体信息"""
        return self.search_gases()

    def get_gas_by_cas(self, cas_no: str) -> Optional[Dict]:
        """根据CAS号获取气体信息"""
        results = self.search_gases(condition='CAS号', value=cas_no)
        return results[0] if results else None

    def get_gases_by_toxicity(self, toxicity_level: str) -> List[Dict]:
        """根据毒性等级获取气体信息（模糊匹配，如 '高毒' 命中 '高毒/致癌'）"""
        return self.search_gases(toxicity_level=toxicity_level)

    def get_toxicity_classes(self) -> List[str]:
        """获取所有已存在的毒性等级（供筛选项使用）"""
        try:
            self.cursor.execute(
                "SELECT DISTINCT 毒性等级 FROM toxic_gases WHERE 毒性等级 IS NOT NULL ORDER BY 毒性等级")
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取毒性等级失败: {e}")
            return []

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

            # 沸点范围（仅统计可解析出数值的记录）
            self.cursor.execute("SELECT 沸点 FROM toxic_gases")
            boiling_points = [v for row in self.cursor.fetchall()
                              if (v := self._parse_number(row[0])) is not None]
            if boiling_points:
                stats['boiling_point_range'] = (
                    f"{min(boiling_points)}℃ 到 {max(boiling_points)}℃")
            else:
                stats['boiling_point_range'] = 'N/A'

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
                    '沸点': '沸点 (℃)',
                    '熔点': '熔点 (℃)',
                    'CAS号': 'CAS 号',
                    'IDLH浓度': 'IDLH 浓度',
                    'MAC浓度': 'MAC 浓度',
                    'LC50': 'LC50(体积分数)/10^-6',
                })
                df.to_excel(file_path, index=False)
                logger.debug(f"数据已导出到: {file_path}")
        except Exception as e:
            logger.debug(f"导出失败: {e}")

    def close(self):
        """关闭数据库连接"""
        self.conn.close()
        logger.debug("数据库连接已关闭")
