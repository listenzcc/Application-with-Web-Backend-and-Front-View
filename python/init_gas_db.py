from explorer.toxic_gas import ToxicGasDatabase
from explorer import logger


def example_usage():
    # 1. 初始化数据库（会自动从Excel导入数据）
    # 注意：需要先将你的Excel保存为 toxic_gases.xlsx
    db = ToxicGasDatabase(excel_path='data/gas/a.xlsx')

    # 2. 查询所有气体
    logger.debug("\n=== 所有气体信息 ===")
    all_gases = db.get_all_gases()
    for gas in all_gases:
        logger.debug(f"{gas['气体名称']} ({gas['分子式']}) - 毒性: {gas['毒性等级']}")

    # 3. 按毒性等级查询
    logger.debug("\n=== 高毒性气体 ===")
    high_toxic = db.get_gases_by_toxicity('高毒')
    for gas in high_toxic:
        logger.debug(f"{gas['气体名称']}: IDLH浓度={gas['IDLH浓度']}")

    # 4. 添加新气体
    logger.debug("\n=== 添加新气体 ===")
    new_gas = {
        '气体名称': '溴气',
        '分子式': 'Br₂',
        'CAS号': '7726-95-6',
        '分子量': 159.808,
        '毒性等级': '高毒',
        '沸点_C': 58.8,
        '熔点_C': -7.2,
        'IDLH浓度': '3 ppm',
        'MAC浓度': '0.5 mg/m³'
    }
    db.add_gas(new_gas)

    # 5. 更新气体信息
    logger.debug("\n=== 更新气体信息 ===")
    update_data = {
        '毒性等级': '剧毒',
        'MAC浓度': '0.1 mg/m³'
    }
    db.update_gas('Cl2', update_data)

    # 6. 复杂查询：沸点在-50℃到50℃之间的气体
    logger.debug("\n=== 沸点在-50℃到50℃之间的气体 ===")
    gases_in_range = db.search_gases(
        min_boiling_point=-50, max_boiling_point=50)
    for gas in gases_in_range:
        logger.debug(f"{gas['气体名称']}: 沸点={gas['沸点_C']}℃")

    # 7. 获取统计信息
    logger.debug("\n=== 数据库统计 ===")
    stats = db.get_statistics()
    for key, value in stats.items():
        logger.debug(f"{key}: {value}")

    # 8. 导出到Excel
    # db.export_to_excel('toxic_gases_export.xlsx')

    # 9. 删除气体
    logger.debug("\n=== 删除气体 ===")
    db.delete_gas('Br₂')

    # 关闭数据库
    db.close()


if __name__ == "__main__":
    # 当数据库不存在时，重新初始化数据库
    example_usage()
