import os

import pandas as pd

from explorer.chemical import ChemicalDatabase
from explorer import logger


# 化学品示例数据文件（若文件不存在或为空则自动生成）
CHEMICAL_EXCEL = 'data/chemical/a-20260911.xlsx'

# 示例数据列，与 ChemicalDatabase.FIELDS 的 Excel 列名保持一致
SAMPLE_COLUMNS = [
    '化学品名称', '别名', '分子式', 'CAS号', '分子量',
    '危险性类别', '物理状态', '沸点 (℃)', '熔点 (℃)', '闪点 (℃)',
    '爆炸下限 (%)', '爆炸上限 (%)', '相对密度', '溶解性', '危险特性',
]

SAMPLE_DATA = [
    ['甲烷', '沼气', 'CH4', '74-82-8', 16.04, '易燃气体', '气态', -161.5, -182.5, -188.0,
        5.0, 15.0, 0.55, '微溶于水', '极易燃，与空气混合形成爆炸性混合物'],
    ['乙烷', '二甲氧基甲烷', 'C2H6', '74-84-0', 30.07, '易燃气体', '气态', -88.6, -182.8, -135.0,
        3.0, 12.5, 1.05, '微溶于水', '易燃，遇明火、高热有燃烧爆炸危险'],
    ['丙烷', '液化石油气组分', 'C3H8', '74-98-6', 44.10, '易燃气体', '气态', -42.1, -187.7, -104.0,
        2.1, 9.5, 1.56, '微溶于水', '极易燃，气体比空气重，易在低处聚集'],
    ['乙炔', '电石气', 'C2H2', '74-86-2', 26.04, '易燃气体', '气态', -84.0, -80.8,
        None, 2.1, 80.0, 0.91, '微溶于水', '极易燃易爆，与空气形成爆炸性混合物'],
    ['氢气', '氢', 'H2', '1333-74-0', 2.02, '易燃气体', '气态', -252.9, -259.2,
        None, 4.0, 75.0, 0.07, '难溶于水', '极易燃易爆，扩散系数大'],
    ['一氧化碳', '煤气', 'CO', '630-08-0', 28.01, '有毒气体', '气态', -191.5, -205.0,
        None, 12.5, 74.0, 0.97, '微溶于水', '剧毒、易燃，吸入致组织缺氧'],
    ['硫化氢', '氢硫酸', 'H2S', '7783-06-4', 34.08, '有毒气体', '气态', -60.3, -85.5,
        None, 4.3, 46.0, 1.19, '溶于水', '剧毒、易燃，低浓度有臭鸡蛋味'],
    ['氨', '氨气', 'NH3', '7664-41-7', 17.03, '有毒气体', '气态', -33.3, -77.7,
        None, 15.0, 28.0, 0.60, '极易溶于水', '有毒、可燃，对呼吸道和眼有强烈刺激'],
    ['氯气', '氯', 'Cl2', '7782-50-5', 70.90, '有毒气体', '气态', -34.04, -101.5,
        None, None, None, 2.49, '溶于水', '剧毒、强氧化性，对呼吸道有强腐蚀作用'],
    ['二氧化硫', '亚硫酸酐', 'SO2', '7446-09-5', 64.07, '有毒气体', '气态', -10.0, -75.5,
        None, None, None, 1.43, '溶于水', '有毒、腐蚀性，刺激眼和呼吸道'],
    ['苯', '纯苯', 'C6H6', '71-43-2', 78.11, '易燃液体', '液态', 80.1, 5.5, -11.0,
        1.2, 8.0, 0.88, '微溶于水', '易燃、致癌，蒸气与空气形成爆炸性混合物'],
    ['甲醇', '木醇', 'CH4O', '67-56-1', 32.04, '易燃液体', '液态', 64.7, -97.8, 11.0,
        6.0, 36.5, 0.79, '溶于水', '易燃、有毒，误饮可致失明甚至死亡'],
    ['乙醇', '酒精', 'C2H6O', '64-17-5', 46.07, '易燃液体', '液态', 78.3, -114.1, 13.0,
        3.3, 19.0, 0.79, '溶于水', '易燃，蒸气与空气形成爆炸性混合物'],
    ['丙酮', '二甲基酮', 'C3H6O', '67-64-1', 58.08, '易燃液体', '液态', 56.5, -94.6, -20.0,
        2.5, 13.0, 0.79, '溶于水', '极易燃，蒸气比空气重，易积聚'],
    ['汽油', '车用汽油', 'C4~C12', '86290-81-5', 95.00, '易燃液体', '液态', 40.0, -60.0, -50.0,
        1.4, 7.6, 0.75, '不溶于水', '极易燃，蒸气与空气形成爆炸性混合物'],
]


def ensure_sample_excel(excel_path: str = CHEMICAL_EXCEL) -> str:
    """文件不存在或为空时生成示例 Excel，否则保留用户已有文件"""
    if os.path.exists(excel_path) and os.path.getsize(excel_path) > 0:
        logger.debug(f"已存在非空数据文件，跳过示例数据生成: {excel_path}")
        return excel_path

    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    df = pd.DataFrame(SAMPLE_DATA, columns=SAMPLE_COLUMNS)
    df.to_excel(excel_path, index=False)
    logger.debug(f"已生成示例数据文件: {excel_path}（{len(df)} 条）")
    return excel_path


def example_usage():
    # 1. 初始化数据库（会自动从Excel导入数据）
    excel_path = ensure_sample_excel()
    db = ChemicalDatabase(excel_path=excel_path)

    # 2. 查询所有化学品
    logger.debug("\n=== 所有化学品信息 ===")
    all_chemicals = db.get_all_chemicals()
    for chemical in all_chemicals:
        logger.debug(
            f"{chemical['化学品名称']} ({chemical['分子式']}) - 危险性类别: {chemical['危险性类别']}")

    # 3. 按危险性类别查询
    logger.debug("\n=== 有毒气体 ===")
    toxic = db.get_chemicals_by_hazard('有毒气体')
    for chemical in toxic:
        logger.debug(f"{chemical['化学品名称']}: 危险特性={chemical['危险特性']}")

    # 4. 添加新化学品
    # new_chemical = {
    #     '化学品名称': '甲苯',
    #     '别名': '甲基苯',
    #     '分子式': 'C7H8',
    #     'CAS号': '108-88-3',
    #     '分子量': 92.14,
    #     '危险性类别': '易燃液体',
    #     '物理状态': '液态',
    #     '沸点_C': 110.6,
    #     '熔点_C': -94.9,
    #     '闪点_C': 4.4,
    #     '爆炸下限': 1.2,
    #     '爆炸上限': 7.1,
    #     '相对密度': 0.87,
    #     '溶解性': '不溶于水',
    #     '危险特性': '易燃、有毒，蒸气与空气形成爆炸性混合物'
    # }
    # db.add_chemical(new_chemical)

    # 5. 更新化学品信息
    # update_data = {
    #     '危险性类别': '高毒',
    #     '危险特性': '剧毒、易燃'
    # }
    # db.update_chemical('Cl2', update_data)

    # 6. 复杂查询：沸点在-50℃到50℃之间的化学品
    logger.debug("\n=== 沸点在-50℃到50℃之间的化学品 ===")
    chemicals_in_range = db.search_chemicals(
        min_boiling_point=-50, max_boiling_point=50)
    for chemical in chemicals_in_range:
        logger.debug(f"{chemical['化学品名称']}: 沸点={chemical['沸点_C']}℃")

    # 7. 获取统计信息
    logger.debug("\n=== 数据库统计 ===")
    stats = db.get_statistics()
    for key, value in stats.items():
        logger.debug(f"{key}: {value}")

    # 8. 导出到Excel
    # db.export_to_excel('chemical_export.xlsx')

    # 9. 删除化学品
    # db.delete_chemical('C7H8')

    # 关闭数据库
    db.close()


if __name__ == "__main__":
    # 当数据库不存在时，重新初始化数据库
    example_usage()
