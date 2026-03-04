"""
报告生成服务模块
提供PDF和Excel格式的审核报告生成功能
"""

import os
from pathlib import Path
from datetime import datetime
from typing import List
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

BASE_DIR = Path.home() / "cad-review"


def generate_pdf(project, results: List, version: int) -> str:
    """
    生成PDF审核报告
    
    Args:
        project: 项目对象
        results: 审核结果列表
        version: 审核版本号
    
    Returns:
        PDF文件路径
    """
    project_dir = BASE_DIR / "projects" / project.id / "reports"
    project_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_path = project_dir / f"report_v{version}.pdf"
    
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        spaceAfter=30
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=20,
        spaceAfter=10
    )
    
    story = []
    
    story.append(Paragraph("室内装饰施工图审核报告", title_style))
    story.append(Spacer(1, 10*mm))
    
    story.append(Paragraph(f"<b>项目名称：</b>{project.name}", styles['Normal']))
    story.append(Paragraph(f"<b>审核日期：</b>{datetime.now().strftime('%Y年%m月%d日')}", styles['Normal']))
    story.append(Paragraph(f"<b>审核版本：</b>V{version}", styles['Normal']))
    story.append(Spacer(1, 10*mm))
    
    index_results = [r for r in results if r.type == "index"]
    dimension_results = [r for r in results if r.type == "dimension"]
    material_results = [r for r in results if r.type == "material"]
    
    total = len(results)
    story.append(Paragraph(f"<b>问题总数：</b>{total}个", styles['Normal']))
    story.append(Paragraph(f"<b>索引问题：</b>{len(index_results)}个", styles['Normal']))
    story.append(Paragraph(f"<b>尺寸问题：</b>{len(dimension_results)}个", styles['Normal']))
    story.append(Paragraph(f"<b>材料问题：</b>{len(material_results)}个", styles['Normal']))
    story.append(Spacer(1, 10*mm))
    
    if index_results:
        story.append(Paragraph("一、索引问题", heading_style))
        for r in index_results:
            story.append(Paragraph(f"• {r.description}", styles['Normal']))
        story.append(Spacer(1, 5*mm))
    
    if dimension_results:
        story.append(Paragraph("二、尺寸问题", heading_style))
        for r in dimension_results:
            story.append(Paragraph(f"• {r.description}", styles['Normal']))
        story.append(Spacer(1, 5*mm))
    
    if material_results:
        story.append(Paragraph("三、材料问题", heading_style))
        for r in material_results:
            story.append(Paragraph(f"• {r.description}", styles['Normal']))
    
    if total == 0:
        story.append(Paragraph("未发现审核问题", styles['Normal']))
    
    doc.build(story)
    return str(pdf_path)


def generate_excel(project, results: List, version: int) -> str:
    """
    生成Excel审核报告
    
    Args:
        project: 项目对象
        results: 审核结果列表
        version: 审核版本号
    
    Returns:
        Excel文件路径
    """
    project_dir = BASE_DIR / "projects" / project.id / "reports"
    project_dir.mkdir(parents=True, exist_ok=True)
    
    excel_path = project_dir / f"report_v{version}.xlsx"
    
    wb = Workbook()
    
    ws_overview = wb.active
    ws_overview.title = "概览"
    
    header_font = Font(bold=True, size=12)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font_white = Font(bold=True, size=12, color="FFFFFF")
    
    ws_overview.append(["项目名称", project.name])
    ws_overview.append(["审核日期", datetime.now().strftime('%Y年%m月%d日')])
    ws_overview.append(["审核版本", f"V{version}"])
    ws_overview.append([])
    
    index_results = [r for r in results if r.type == "index"]
    dimension_results = [r for r in results if r.type == "dimension"]
    material_results = [r for r in results if r.type == "material"]
    
    ws_overview.append(["问题统计"])
    ws_overview.append(["问题类型", "数量"])
    ws_overview.append(["索引问题", len(index_results)])
    ws_overview.append(["尺寸问题", len(dimension_results)])
    ws_overview.append(["材料问题", len(material_results)])
    ws_overview.append(["总计", len(results)])
    
    def create_sheet(wb, title, data):
        ws = wb.create_sheet(title)
        ws.append(["图号A", "图号B", "位置", "值A", "值B", "问题描述", "严重程度"])
        
        for cell in ws[1]:
            cell.font = header_font_white
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        
        for row in data:
            severity = row.get("severity", "warning")
            fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid") if severity == "error" else \
                   PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid") if severity == "warning" else \
                   PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
            
            ws.append([
                row.get("sheet_no_a", ""),
                row.get("sheet_no_b", ""),
                row.get("location", ""),
                row.get("value_a", ""),
                row.get("value_b", ""),
                row.get("description", ""),
                severity
            ])
            
            for cell in ws[len(ws)]:
                if cell.column != 7:
                    cell.fill = fill
        
        return ws
    
    index_data = [{"sheet_no_a": r.sheet_no_a, "sheet_no_b": r.sheet_no_b, "location": r.location, 
                   "value_a": r.value_a, "value_b": r.value_b, "description": r.description, "severity": r.severity} for r in index_results]
    if index_data:
        create_sheet(wb, "索引问题", index_data)
    
    dimension_data = [{"sheet_no_a": r.sheet_no_a, "sheet_no_b": r.sheet_no_b, "location": r.location,
                       "value_a": r.value_a, "value_b": r.value_b, "description": r.description, "severity": r.severity} for r in dimension_results]
    if dimension_data:
        create_sheet(wb, "尺寸问题", dimension_data)
    
    material_data = [{"sheet_no_a": r.sheet_no_a, "sheet_no_b": r.sheet_no_b, "location": r.location,
                     "value_a": r.value_a, "value_b": r.value_b, "description": r.description, "severity": r.severity} for r in material_results]
    if material_data:
        create_sheet(wb, "材料问题", material_data)
    
    wb.save(str(excel_path))
    return str(excel_path)
