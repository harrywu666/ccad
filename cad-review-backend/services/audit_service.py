"""
审核服务模块
提供索引核对、尺寸核对、材料核对功能
"""

import json
from typing import List, Dict
from models import JsonData, AuditResult


def audit_indexes(project_id: str, audit_version: int, db) -> List[AuditResult]:
    """
    索引核对：检测断链和孤立索引
    
    Args:
        project_id: 项目ID
        audit_version: 审核版本号
        db: 数据库会话
    
    Returns:
        审核结果列表
    """
    json_list = db.query(JsonData).filter(
        JsonData.project_id == project_id,
        JsonData.is_latest == 1
    ).all()
    
    all_indexes = {}
    sheet_indexes = {}
    
    for json_data in json_list:
        if not json_data.json_path:
            continue
        
        try:
            with open(json_data.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            continue
        
        sheet_no = json_data.sheet_no or "unknown"
        indexes = data.get("indexes", [])
        
        sheet_indexes[sheet_no] = indexes
        
        for idx in indexes:
            index_no = idx.get("index_no", "")
            target_sheet = idx.get("target_sheet", "")
            
            key = f"{sheet_no}->{index_no}"
            all_indexes[key] = {
                "source_sheet": sheet_no,
                "index_no": index_no,
                "target_sheet": target_sheet,
                "position": idx.get("position", [])
            }
    
    issues = []
    
    for key, idx_info in all_indexes.items():
        target = idx_info["target_sheet"]
        index_no = idx_info["index_no"]
        
        if target not in sheet_indexes:
            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="index",
                severity="error",
                sheet_no_a=idx_info["source_sheet"],
                sheet_no_b=target,
                location=f"索引{index_no}",
                description=f"图纸{idx_info['source_sheet']}中存在索引{index_no}指向{target}，但该图纸不存在"
            )
            db.add(issue)
            issues.append(issue)
        else:
            target_indexes = sheet_indexes[target]
            found = False
            for ti in target_indexes:
                if ti.get("index_no") == index_no:
                    found = True
                    break
            
            if not found:
                issue = AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="index",
                    severity="error",
                    sheet_no_a=idx_info["source_sheet"],
                    sheet_no_b=target,
                    location=f"索引{index_no}",
                    description=f"图纸{idx_info['source_sheet']}中索引{index_no}指向{target}，但{target}中未找到对应的{index_no}号大样"
                )
                db.add(issue)
                issues.append(issue)
    
    db.commit()
    return issues


def audit_dimensions(project_id: str, audit_version: int, db) -> List[AuditResult]:
    """
    尺寸核对：基于索引关系比对平立面尺寸
    
    Args:
        project_id: 项目ID
        audit_version: 审核版本号
        db: 数据库会话
    
    Returns:
        审核结果列表
    """
    json_list = db.query(JsonData).filter(
        JsonData.project_id == project_id,
        JsonData.is_latest == 1
    ).all()
    
    issues = []
    
    for i, json_data_a in enumerate(json_list):
        if not json_data_a.json_path:
            continue
        
        try:
            with open(json_data_a.json_path, "r", encoding="utf-8") as f:
                data_a = json.load(f)
        except:
            continue
        
        indexes_a = data_a.get("indexes", [])
        
        for idx in indexes_a:
            target_sheet = idx.get("target_sheet", "")
            if not target_sheet:
                continue
            
            json_data_b = None
            for jd in json_list:
                if jd.sheet_no == target_sheet:
                    json_data_b = jd
                    break
            
            if not json_data_b or not json_data_b.json_path:
                continue
            
            try:
                with open(json_data_b.json_path, "r", encoding="utf-8") as f:
                    data_b = json.load(f)
            except:
                continue
            
            dims_a = data_a.get("dimensions", [])
            dims_b = data_b.get("dimensions", [])
            
            dim_map_a = {d.get("id"): d for d in dims_a}
            
            for dim_b in dims_b:
                pos_b = dim_b.get("defpoint", [0, 0])
                value_b = dim_b.get("value", 0)
                
                for dim_a in dims_a:
                    pos_a = dim_a.get("defpoint", [0, 0])
                    value_a = dim_a.get("value", 0)
                    
                    import math
                    distance = math.sqrt((pos_a[0] - pos_b[0])**2 + (pos_a[1] - pos_b[1])**2)
                    
                    if distance < 500 and abs(value_a - value_b) > 10:
                        issue = AuditResult(
                            project_id=project_id,
                            audit_version=audit_version,
                            type="dimension",
                            severity="warning",
                            sheet_no_a=json_data_a.sheet_no,
                            sheet_no_b=json_data_b.sheet_no,
                            location=f"位置({int(pos_a[0])},{int(pos_a[1])})",
                            value_a=str(value_a),
                            value_b=str(value_b),
                            description=f"平面图{json_data_a.sheet_no}与立面图{json_data_b.sheet_no}同一位置尺寸不一致：平面图{value_a}mm，立面图{value_b}mm，差值{abs(value_a - value_b)}mm"
                        )
                        db.add(issue)
                        issues.append(issue)
                        break
    
    db.commit()
    return issues


def audit_materials(project_id: str, audit_version: int, db) -> List[AuditResult]:
    """
    材料核对：检测未定义/未使用的材料
    
    Args:
        project_id: 项目ID
        audit_version: 审核版本号
        db: 数据库会话
    
    Returns:
        审核结果列表
    """
    json_list = db.query(JsonData).filter(
        JsonData.project_id == project_id,
        JsonData.is_latest == 1
    ).all()
    
    issues = []
    
    for json_data in json_list:
        if not json_data.json_path:
            continue
        
        try:
            with open(json_data.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            continue
        
        material_table = data.get("material_table", [])
        materials = data.get("materials", [])
        
        table_codes = {m.get("code", "") for m in material_table}
        used_codes = {m.get("code", "") for m in materials}
        
        for mat in materials:
            code = mat.get("code", "")
            if code and code not in table_codes:
                issue = AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="material",
                    severity="error",
                    sheet_no_a=json_data.sheet_no,
                    location=f"材料标注{code}",
                    description=f"图纸{json_data.sheet_no}中使用了材料编号{code}，但材料表中未找到定义"
                )
                db.add(issue)
                issues.append(issue)
        
        for table_item in material_table:
            code = table_item.get("code", "")
            if code and code not in used_codes:
                issue = AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="material",
                    severity="info",
                    sheet_no_a=json_data.sheet_no,
                    location=f"材料表{code}",
                    description=f"材料表中定义了材料编号{code}（{table_item.get('name', '')}），但在图纸中未使用"
                )
                db.add(issue)
                issues.append(issue)
    
    db.commit()
    return issues
