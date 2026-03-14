"""services.dxf 包 — 聚合 re-export 全部公共名称。"""

__all__ = [
    # geo_utils
    "_safe_float", "_point_xy", "_point_xyz", "_classify_elevation_band",
    "_point_in_range", "_point_in_any_range",
    "_distance", "_point_distance_to_insert", "_collect_virtual_entity_points",
    "_bbox_center", "_bbox_range", "_bbox_contains_point", "_expand_bbox",
    "_bbox_area", "_bbox_size", "_bbox_almost_equal", "_is_axis_aligned_rect",
    # text_utils
    "MODEL_LAYOUT_NAMES", "INDEX_KEYWORDS", "TITLE_KEYWORDS", "MATERIAL_LAYER_KEYWORDS",
    "_normalize_name", "_is_model_layout", "_sanitize_filename",
    "_extract_sheet_no_from_text", "_is_standalone_sheet_no_text", "_is_sheet_no_like",
    "_extract_sheet_name_from_layout", "_is_generic_layout_name",
    "_normalize_plain_text", "_attr_list", "_is_numeric_like_text", "_parse_numeric_text",
    "_display_scale", "_extract_layout_page_range", "_infer_paper_size_hint",
    "_collect_text_entities_from_space", "_collect_nested_texts", "_collect_text_entities",
    # oda_converter
    "get_oda_path", "dwg_batch_to_dxf", "dwg_to_dxf",
    # viewport
    "calc_model_range", "get_visible_layers", "_pick_main_viewport",
    "_collect_viewports", "_collect_layer_states",
    "_collect_insert_head_points", "_estimate_insert_visual_anchor",
    "_estimate_insert_visual_bbox", "_estimate_index_anchor",
    # layout_detection
    "_collect_layout_frame_candidates", "_object_position",
    "_infer_fragment_identity_from_texts", "_detect_layout_frames",
    "_build_layout_fragments",
    # entity_extraction
    "_DIMENSION_QUERIES",
    "_extract_dimensions", "_collect_nested_dimensions", "_extract_pseudo_texts",
    "_looks_like_detail_label", "_looks_like_index_number", "_pick_generic_index_pair",
    "_extract_detail_title_from_insert", "_collect_detail_titles_from_space",
    "_extract_insert_info",
    # material_extraction
    "_mleader_position", "_mleader_content",
    "_extract_materials_from_space", "_extract_materials",
    "_pair_material_rows_from_text", "_extract_material_table",
    # pipeline
    "extract_layout", "_convert_dwg_and_extract", "_get_cached_layout_payload",
    "_layout_payload_cache",
    "read_layout_page_range_from_dwg", "read_layout_indexes_from_dwg",
    "read_layout_detail_titles_from_dwg", "read_layout_structure_from_dwg",
    "_write_layout_json", "_list_dwg_paths", "process_dwg_files",
]

from services.dxf.entity_extraction import (  # noqa: F401
    _DIMENSION_QUERIES,
    _collect_detail_titles_from_space,
    _collect_nested_dimensions,
    _extract_detail_title_from_insert,
    _extract_dimensions,
    _extract_insert_info,
    _extract_pseudo_texts,
    _looks_like_detail_label,
    _looks_like_index_number,
    _pick_generic_index_pair,
)
from services.dxf.geo_utils import (  # noqa: F401
    _bbox_almost_equal,
    _bbox_area,
    _bbox_center,
    _bbox_contains_point,
    _bbox_range,
    _bbox_size,
    _classify_elevation_band,
    _collect_virtual_entity_points,
    _distance,
    _expand_bbox,
    _is_axis_aligned_rect,
    _point_distance_to_insert,
    _point_in_any_range,
    _point_in_range,
    _point_xy,
    _point_xyz,
    _safe_float,
)
from services.dxf.layout_detection import (  # noqa: F401
    _build_layout_fragments,
    _collect_layout_frame_candidates,
    _detect_layout_frames,
    _infer_fragment_identity_from_texts,
    _object_position,
)
from services.dxf.material_extraction import (  # noqa: F401
    _extract_material_table,
    _extract_materials,
    _extract_materials_from_space,
    _mleader_content,
    _mleader_position,
    _pair_material_rows_from_text,
)
from services.dxf.oda_converter import (  # noqa: F401
    dwg_batch_to_dxf,
    dwg_to_dxf,
    get_oda_path,
)
from services.dxf.pipeline import (  # noqa: F401
    _convert_dwg_and_extract,
    _get_cached_layout_payload,
    _layout_payload_cache,
    _list_dwg_paths,
    _write_layout_json,
    extract_layout,
    process_dwg_files,
    read_layout_detail_titles_from_dwg,
    read_layout_indexes_from_dwg,
    read_layout_page_range_from_dwg,
    read_layout_structure_from_dwg,
)
from services.dxf.text_utils import (  # noqa: F401
    INDEX_KEYWORDS,
    MATERIAL_LAYER_KEYWORDS,
    MODEL_LAYOUT_NAMES,
    TITLE_KEYWORDS,
    _attr_list,
    _collect_nested_texts,
    _collect_text_entities,
    _collect_text_entities_from_space,
    _display_scale,
    _extract_layout_page_range,
    _extract_sheet_name_from_layout,
    _extract_sheet_no_from_text,
    _infer_paper_size_hint,
    _is_generic_layout_name,
    _is_model_layout,
    _is_numeric_like_text,
    _is_sheet_no_like,
    _is_standalone_sheet_no_text,
    _normalize_name,
    _normalize_plain_text,
    _parse_numeric_text,
    _sanitize_filename,
)
from services.dxf.viewport import (  # noqa: F401
    _collect_insert_head_points,
    _collect_layer_states,
    _collect_viewports,
    _estimate_index_anchor,
    _estimate_insert_visual_anchor,
    _estimate_insert_visual_bbox,
    _pick_main_viewport,
    calc_model_range,
    get_visible_layers,
)
