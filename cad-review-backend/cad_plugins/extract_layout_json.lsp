; CCAD AutoCAD 插件：按布局导出 JSON（一个布局一个文件，跳过 Model）
; AutoCAD 2024 可用（由 COM 自动化调用）
;
; 用法：
;   (load "C:/path/to/extract_layout_json.lsp")
;   (ccad:export-layout-json "C:/out/jsons" "C:/out/jsons/demo.__done__.flag")

(vl-load-com)

; -------------------------
; 基础工具
; -------------------------

(defun ccad:is-true (v)
  (or (= v T) (= v 1) (= v :vlax-true))
)

(defun ccad:bool-json (v)
  (if (ccad:is-true v) "true" "false")
)

(defun ccad:num-json (v)
  (if (numberp v) (rtos v 2 6) "0")
)

(defun ccad:str-replace-all (src old new / pos)
  (if (or (null src) (null old) (= old ""))
    src
    (progn
      (while (setq pos (vl-string-search old src))
        (setq src (strcat (substr src 1 pos) new (substr src (+ pos (strlen old) 1))))
      )
      src
    )
  )
)

(defun ccad:json-escape (s / out)
  (if (null s) (setq s ""))
  (setq out s)
  (setq out (ccad:str-replace-all out "\\" "\\\\"))
  (setq out (ccad:str-replace-all out "\"" "\\\""))
  (setq out (ccad:str-replace-all out "\n" "\\n"))
  (setq out (ccad:str-replace-all out "\r" "\\r"))
  out
)

(defun ccad:safe-file (s / out)
  (setq out s)
  (if (null out) (setq out "layout"))
  (setq out (ccad:str-replace-all out "\\" "_"))
  (setq out (ccad:str-replace-all out "/" "_"))
  (setq out (ccad:str-replace-all out ":" "_"))
  (setq out (ccad:str-replace-all out "*" "_"))
  (setq out (ccad:str-replace-all out "?" "_"))
  (setq out (ccad:str-replace-all out "\"" "_"))
  (setq out (ccad:str-replace-all out "<" "_"))
  (setq out (ccad:str-replace-all out ">" "_"))
  (setq out (ccad:str-replace-all out "|" "_"))
  (if (= out "") (setq out "layout"))
  out
)

(defun ccad:join (lst sep / out)
  (if (null lst)
    ""
    (progn
      (setq out (car lst))
      (foreach x (cdr lst)
        (setq out (strcat out sep x))
      )
      out
    )
  )
)

(defun ccad:point-json (pt / x y)
  (if (and pt (listp pt))
    (progn
      (setq x (if (numberp (car pt)) (rtos (car pt) 2 6) "0"))
      (setq y (if (numberp (cadr pt)) (rtos (cadr pt) 2 6) "0"))
      (strcat "[" x "," y "]")
    )
    "[0,0]"
  )
)

(defun ccad:variant->list (v / vv)
  (cond
    ((null v) nil)
    ((= (type v) 'LIST) v)
    ((= (type v) 'SAFEARRAY) (vlax-safearray->list v))
    ((= (type v) 'VARIANT)
      (setq vv (vlax-variant-value v))
      (if (= (type vv) 'SAFEARRAY) (vlax-safearray->list vv) nil)
    )
    (T nil)
  )
)

(defun ccad:get-prop (obj prop default / res)
  (setq res (vl-catch-all-apply 'vlax-get-property (list obj prop)))
  (if (vl-catch-all-error-p res) default res)
)

(defun ccad:contains (src key)
  (if (and src key)
    (if (vl-string-search (strcase key) (strcase src)) T nil)
    nil
  )
)

(defun ccad:contains-any (src keys / hit)
  (setq hit nil)
  (if src
    (foreach k keys
      (if (and (not hit) (ccad:contains src k))
        (setq hit T)
      )
    )
  )
  hit
)

(defun ccad:first-token (s / txt i len ch tok)
  (setq txt (vl-string-trim " \t\r\n" (if s s "")))
  (setq i 1)
  (setq len (strlen txt))
  (setq tok "")
  (while (and (<= i len) (/= (substr txt i 1) " "))
    (setq tok (strcat tok (substr txt i 1)))
    (setq i (1+ i))
  )
  tok
)

(defun ccad:rest-token (s / txt i len rest)
  (setq txt (vl-string-trim " \t\r\n" (if s s "")))
  (setq i 1)
  (setq len (strlen txt))
  (while (and (<= i len) (/= (substr txt i 1) " "))
    (setq i (1+ i))
  )
  (while (and (<= i len) (= (substr txt i 1) " "))
    (setq i (1+ i))
  )
  (if (<= i len) (substr txt i) "")
)

(defun ccad:safe-str (v)
  (cond
    ((null v) "")
    ((vl-catch-all-error-p v) "")
    ((= (type v) 'STR) v)
    (T (vl-princ-to-string v))
  )
)

(defun ccad:normalize-text (s / out)
  (setq out (ccad:safe-str s))
  (setq out (ccad:str-replace-all out "\\P" " "))
  (setq out (ccad:str-replace-all out "\\p" " "))
  (setq out (ccad:str-replace-all out "{\\L" ""))
  (setq out (ccad:str-replace-all out "{\\l" ""))
  (setq out (ccad:str-replace-all out "{\\O" ""))
  (setq out (ccad:str-replace-all out "{\\o" ""))
  (setq out (ccad:str-replace-all out "}" ""))
  (setq out (vl-string-trim " \t\r\n" out))
  out
)

(defun ccad:numeric-string-p (s / txt i len ch ok has-digit)
  (setq txt (strcase (ccad:normalize-text s)))
  (setq txt (ccad:str-replace-all txt "MM" ""))
  (setq txt (ccad:str-replace-all txt "," ""))
  (setq txt (ccad:str-replace-all txt " " ""))
  (setq i 1)
  (setq len (strlen txt))
  (setq ok T)
  (setq has-digit nil)
  (while (and ok (<= i len))
    (setq ch (substr txt i 1))
    (if (wcmatch ch "#")
      (setq has-digit T)
      (if (not (or (= ch ".") (= ch "-") (= ch "+")))
        (setq ok nil)
      )
    )
    (setq i (1+ i))
  )
  (and ok has-digit)
)

(defun ccad:number-string (s / txt)
  (setq txt (strcase (ccad:normalize-text s)))
  (setq txt (ccad:str-replace-all txt "MM" ""))
  (setq txt (ccad:str-replace-all txt "," ""))
  (setq txt (ccad:str-replace-all txt " " ""))
  txt
)

(defun ccad:code-like-p (s / u)
  (setq u (strcase (if s s "")))
  (and (> (strlen u) 0) (wcmatch u "*[0-9]*") (< (strlen u) 32))
)

(defun ccad:sheet-no-like-p (s)
  (and
    (ccad:code-like-p s)
    (or
      (if (vl-string-search "-" s) T nil)
      (if (vl-string-search "." s) T nil)
      (if (vl-string-search "_" s) T nil)
    )
  )
)

(defun ccad:guess-sheet-no (layout-name / t)
  (setq t (ccad:first-token (ccad:normalize-text layout-name)))
  (if (ccad:sheet-no-like-p t) t "")
)

(defun ccad:guess-sheet-name (layout-name sheet-no / s)
  (setq s (ccad:normalize-text layout-name))
  (if (and sheet-no (/= sheet-no ""))
    (setq s (vl-string-subst "" sheet-no s))
  )
  (setq s (vl-string-trim " -_:.|" s))
  s
)

; -------------------------
; 视口信息 VIEWPORT
; -------------------------

(defun ccad:viewport-items-json (layout-name / ss i ename ed obj h center w hgt layer vid cscale items item clayer)
  (setq items '())
  (setq clayer (getvar "CLAYER"))
  (setq ss (ssget "_X" (list (cons 0 "VIEWPORT") (cons 410 layout-name))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ename  (ssname ss i))
        (setq ed     (entget ename))
        (setq obj    (vlax-ename->vla-object ename))
        (setq h      (cdr (assoc 5 ed)))
        (setq center (cdr (assoc 10 ed)))
        (setq hgt    (cdr (assoc 40 ed)))
        (setq w      (cdr (assoc 41 ed)))
        (setq layer  (cdr (assoc 8 ed)))
        (setq vid    (cdr (assoc 69 ed)))
        (setq cscale (ccad:get-prop obj 'CustomScale 1.0))

        (setq item
          (strcat
            "{"
            "\"id\":\"" (ccad:json-escape (if h h "")) "\","
            "\"viewport_id\":" (if (numberp vid) (itoa vid) "0") ","
            "\"position\":" (ccad:point-json center) ","
            "\"width\":" (ccad:num-json w) ","
            "\"height\":" (ccad:num-json hgt) ","
            "\"scale\":" (ccad:num-json cscale) ","
            "\"layer\":\"" (ccad:json-escape (if layer layer "")) "\","
            "\"active_layer\":\"" (ccad:json-escape clayer) "\","
            "\"frozen_layers\":[]"
            "}"
          )
        )
        (setq items (cons item items))
        (setq i (1+ i))
      )
    )
  )
  (strcat "[" (ccad:join (reverse items) ",") "]")
)

; -------------------------
; 尺寸标注 DIMENSION
; -------------------------

(defun ccad:dim-items-json (layout-name / ss i ename ed obj h val txt p1 p2 tp layer items item)
  (setq items '())
  (setq ss (ssget "_X" (list (cons 0 "DIMENSION") (cons 410 layout-name))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ename (ssname ss i))
        (setq ed    (entget ename))
        (setq obj   (vlax-ename->vla-object ename))
        (setq h     (cdr (assoc 5 ed)))
        (setq val   (cdr (assoc 42 ed)))
        (if (null val) (setq val (ccad:get-prop obj 'Measurement 0.0)))
        (setq txt   (cdr (assoc 1 ed)))
        (if (or (null txt) (= txt "<>")) (setq txt ""))
        (setq p1    (cdr (assoc 10 ed)))
        (setq p2    (cdr (assoc 11 ed)))
        (setq tp    (cdr (assoc 13 ed)))
        (setq layer (cdr (assoc 8 ed)))

        (setq item
          (strcat
            "{"
            "\"id\":\"" (ccad:json-escape (if h h "")) "\","
            "\"value\":" (ccad:num-json val) ","
            "\"display_text\":\"" (ccad:json-escape (ccad:normalize-text txt)) "\","
            "\"layer\":\"" (ccad:json-escape (if layer layer "")) "\","
            "\"source\":\"layout_space\","
            "\"defpoint\":" (ccad:point-json p1) ","
            "\"defpoint2\":" (ccad:point-json p2) ","
            "\"text_position\":" (ccad:point-json tp)
            "}"
          )
        )
        (setq items (cons item items))
        (setq i (1+ i))
      )
    )
  )
  (strcat "[" (ccad:join (reverse items) ",") "]")
)

; -------------------------
; 伪标注文字 TEXT/MTEXT（纯数字）
; -------------------------

(defun ccad:pseudo-text-items-json (layout-name / ss i ename ed obj h typ txt p layer numstr items item)
  (setq items '())
  (setq ss (ssget "_X" (list (cons 0 "TEXT,MTEXT") (cons 410 layout-name))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ename (ssname ss i))
        (setq ed    (entget ename))
        (setq obj   (vlax-ename->vla-object ename))
        (setq h     (cdr (assoc 5 ed)))
        (setq typ   (cdr (assoc 0 ed)))
        (setq layer (cdr (assoc 8 ed)))
        (if (= typ "TEXT")
          (progn
            (setq txt (cdr (assoc 1 ed)))
            (setq p   (cdr (assoc 10 ed)))
          )
          (progn
            (setq txt (ccad:get-prop obj 'TextString ""))
            (setq p   (ccad:variant->list (ccad:get-prop obj 'InsertionPoint nil)))
          )
        )

        (setq txt (ccad:normalize-text txt))
        (if (ccad:numeric-string-p txt)
          (progn
            (setq numstr (ccad:number-string txt))
            (setq item
              (strcat
                "{"
                "\"id\":\"" (ccad:json-escape (if h h "")) "\","
                "\"entity_type\":\"" (ccad:json-escape typ) "\","
                "\"content\":\"" (ccad:json-escape txt) "\","
                "\"numeric_value\":" (ccad:num-json (atof numstr)) ","
                "\"position\":" (ccad:point-json p) ","
                "\"layer\":\"" (ccad:json-escape (if layer layer "")) "\""
                "}"
              )
            )
            (setq items (cons item items))
          )
        )
        (setq i (1+ i))
      )
    )
  )
  (strcat "[" (ccad:join (reverse items) ",") "]")
)

; -------------------------
; INSERT 属性解析（索引符号、标题栏）
; -------------------------

(defun ccad:get-insert-attrs (obj / attrs arr i a tag val out)
  (setq out '())
  (if (ccad:is-true (ccad:get-prop obj 'HasAttributes nil))
    (progn
      (setq attrs (vl-catch-all-apply 'vlax-invoke (list obj 'GetAttributes)))
      (if (not (vl-catch-all-error-p attrs))
        (progn
          (setq arr (ccad:variant->list attrs))
          (if arr
            (foreach a arr
              (setq tag (ccad:normalize-text (ccad:get-prop a 'TagString "")))
              (setq val (ccad:normalize-text (ccad:get-prop a 'TextString "")))
              (setq out (cons (cons tag val) out))
            )
          )
        )
      )
    )
  )
  (reverse out)
)

(defun ccad:attrs-json (attrs / out)
  (setq out '())
  (foreach kv attrs
    (setq out
      (cons
        (strcat
          "{"
          "\"tag\":\"" (ccad:json-escape (car kv)) "\","
          "\"value\":\"" (ccad:json-escape (cdr kv)) "\""
          "}"
        )
        out
      )
    )
  )
  (strcat "[" (ccad:join (reverse out) ",") "]")
)

(defun ccad:attr-find (attrs keys / found)
  (setq found "")
  (foreach kv attrs
    (if (and (= found "") (ccad:contains-any (car kv) keys) (/= (cdr kv) ""))
      (setq found (cdr kv))
    )
  )
  found
)

(defun ccad:attr-find-sheet-no (attrs / out)
  (setq out (ccad:attr-find attrs '("SHEETNO" "SHEET_NO" "DRAWINGNO" "DWGNO" "图号")))
  (if (= out "")
    (foreach kv attrs
      (if (and (= out "") (ccad:sheet-no-like-p (cdr kv)))
        (setq out (cdr kv))
      )
    )
  )
  out
)

(defun ccad:index-or-title-json (layout-name / ss i ename ed obj h bname pos layer attrs attrsj
                                           is-index is-title idx-no idx-target t-sheet-no t-sheet-name
                                           indexes titles first-sheet-no first-sheet-name item)
  (setq indexes '())
  (setq titles '())
  (setq first-sheet-no "")
  (setq first-sheet-name "")

  (setq ss (ssget "_X" (list (cons 0 "INSERT") (cons 410 layout-name))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ename (ssname ss i))
        (setq ed    (entget ename))
        (setq obj   (vlax-ename->vla-object ename))
        (setq h     (cdr (assoc 5 ed)))
        (setq bname (ccad:normalize-text (cdr (assoc 2 ed))))
        (setq pos   (cdr (assoc 10 ed)))
        (setq layer (cdr (assoc 8 ed)))
        (setq attrs (ccad:get-insert-attrs obj))
        (setq attrsj (ccad:attrs-json attrs))

        (setq is-index
          (or
            (ccad:contains-any bname '("INDEX" "索引"))
            (ccad:contains-any (ccad:join (mapcar 'car attrs) "|") '("INDEX" "索引"))
          )
        )
        (setq is-title
          (or
            (ccad:contains-any bname '("TITLE" "SHEET" "图签" "标题"))
            (ccad:contains-any (ccad:join (mapcar 'car attrs) "|") '("图号" "图名" "SHEETNO" "DRAWINGNAME" "SHEETNAME"))
          )
        )

        (if is-index
          (progn
            (setq idx-no (ccad:attr-find attrs '("INDEXNO" "INDEX" "NO" "NUM" "编号" "序号")))
            (setq idx-target (ccad:attr-find attrs '("TARGET" "SHEET" "DRAWING" "图号")))
            (if (= idx-target "")
              (setq idx-target (ccad:attr-find-sheet-no attrs))
            )
            (setq item
              (strcat
                "{"
                "\"id\":\"" (ccad:json-escape (if h h "")) "\","
                "\"block_name\":\"" (ccad:json-escape bname) "\","
                "\"index_no\":\"" (ccad:json-escape idx-no) "\","
                "\"target_sheet\":\"" (ccad:json-escape idx-target) "\","
                "\"position\":" (ccad:point-json pos) ","
                "\"layer\":\"" (ccad:json-escape (if layer layer "")) "\","
                "\"attrs\":" attrsj
                "}"
              )
            )
            (setq indexes (cons item indexes))
          )
        )

        (if is-title
          (progn
            (setq t-sheet-no   (ccad:attr-find-sheet-no attrs))
            (setq t-sheet-name (ccad:attr-find attrs '("SHEETNAME" "DRAWINGNAME" "TITLE" "图名")))
            (if (= t-sheet-name "")
              (foreach kv attrs
                (if (and (= t-sheet-name "") (/= (cdr kv) "") (not (ccad:sheet-no-like-p (cdr kv))))
                  (setq t-sheet-name (cdr kv))
                )
              )
            )

            (if (and (= first-sheet-no "") (/= t-sheet-no "")) (setq first-sheet-no t-sheet-no))
            (if (and (= first-sheet-name "") (/= t-sheet-name "")) (setq first-sheet-name t-sheet-name))

            (setq item
              (strcat
                "{"
                "\"id\":\"" (ccad:json-escape (if h h "")) "\","
                "\"block_name\":\"" (ccad:json-escape bname) "\","
                "\"sheet_no\":\"" (ccad:json-escape t-sheet-no) "\","
                "\"sheet_name\":\"" (ccad:json-escape t-sheet-name) "\","
                "\"position\":" (ccad:point-json pos) ","
                "\"layer\":\"" (ccad:json-escape (if layer layer "")) "\","
                "\"attrs\":" attrsj
                "}"
              )
            )
            (setq titles (cons item titles))
          )
        )

        (setq i (1+ i))
      )
    )
  )

  (list
    (strcat "[" (ccad:join (reverse indexes) ",") "]")
    (strcat "[" (ccad:join (reverse titles) ",") "]")
    first-sheet-no
    first-sheet-name
  )
)

; -------------------------
; 材料引线 MLEADER / LEADER
; -------------------------

(defun ccad:material-layer-p (layer-name)
  (ccad:contains-any (if layer-name layer-name "") '("MAT" "MATERIAL" "材料"))
)

(defun ccad:leader-arrow-point (obj ed / coords pts)
  (setq coords (ccad:variant->list (ccad:get-prop obj 'Coordinates nil)))
  (if (and coords (>= (length coords) 2))
    (list (nth 0 coords) (nth 1 coords))
    (cdr (assoc 10 ed))
  )
)

(defun ccad:leader-items-json (layout-name / items ss i ename ed obj typ h layer txt pos code item)
  (setq items '())

  ; MLEADER
  (setq ss (ssget "_X" (list (cons 0 "MLEADER") (cons 410 layout-name))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ename (ssname ss i))
        (setq ed    (entget ename))
        (setq obj   (vlax-ename->vla-object ename))
        (setq typ   "MLEADER")
        (setq h     (cdr (assoc 5 ed)))
        (setq layer (cdr (assoc 8 ed)))
        (setq txt   (ccad:normalize-text (ccad:get-prop obj 'TextString "")))
        (setq pos   (ccad:leader-arrow-point obj ed))
        (setq code  (ccad:first-token txt))
        (if (not (ccad:code-like-p code)) (setq code ""))

        (if (or (/= txt "") (ccad:material-layer-p layer))
          (progn
            (setq item
              (strcat
                "{"
                "\"id\":\"" (ccad:json-escape (if h h "")) "\","
                "\"entity_type\":\"" typ "\","
                "\"content\":\"" (ccad:json-escape txt) "\","
                "\"code\":\"" (ccad:json-escape code) "\","
                "\"arrow\":" (ccad:point-json pos) ","
                "\"layer\":\"" (ccad:json-escape (if layer layer "")) "\""
                "}"
              )
            )
            (setq items (cons item items))
          )
        )
        (setq i (1+ i))
      )
    )
  )

  ; LEADER
  (setq ss (ssget "_X" (list (cons 0 "LEADER") (cons 410 layout-name))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ename (ssname ss i))
        (setq ed    (entget ename))
        (setq obj   (vlax-ename->vla-object ename))
        (setq typ   "LEADER")
        (setq h     (cdr (assoc 5 ed)))
        (setq layer (cdr (assoc 8 ed)))
        (setq txt   "")
        (setq pos   (ccad:leader-arrow-point obj ed))

        (if (ccad:material-layer-p layer)
          (progn
            (setq item
              (strcat
                "{"
                "\"id\":\"" (ccad:json-escape (if h h "")) "\","
                "\"entity_type\":\"" typ "\","
                "\"content\":\"\","
                "\"code\":\"\","
                "\"arrow\":" (ccad:point-json pos) ","
                "\"layer\":\"" (ccad:json-escape (if layer layer "")) "\""
                "}"
              )
            )
            (setq items (cons item items))
          )
        )
        (setq i (1+ i))
      )
    )
  )

  (strcat "[" (ccad:join (reverse items) ",") "]")
)

; -------------------------
; 材料总表 TABLE 或 TEXT拼合
; -------------------------

(defun ccad:add-pair-unique (pairs seen code name / key)
  (setq key (strcat (strcase code) "|" (strcase name)))
  (if (not (member key seen))
    (list (cons (cons code name) pairs) (cons key seen))
    (list pairs seen)
  )
)

(defun ccad:table-pairs-json (layout-name / pairs seen ss i ename obj rows cols r c0 c1 tmp textss txti ted typ txt line code name out)
  (setq pairs '())
  (setq seen '())

  ; TABLE 提取
  (setq ss (ssget "_X" (list (cons 0 "TABLE") (cons 410 layout-name))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ename (ssname ss i))
        (setq obj   (vlax-ename->vla-object ename))
        (setq rows  (fix (ccad:get-prop obj 'Rows 0)))
        (setq cols  (fix (ccad:get-prop obj 'Columns 0)))
        (setq r 0)
        (while (< r rows)
          (setq c0 (ccad:normalize-text (vl-catch-all-apply 'vla-GetText (list obj r 0))))
          (if (> cols 1)
            (setq c1 (ccad:normalize-text (vl-catch-all-apply 'vla-GetText (list obj r 1))))
            (setq c1 "")
          )
          (if (and (ccad:code-like-p c0) (/= c1 "") (not (ccad:contains-any c1 '("名称" "NAME" "材质"))))
            (progn
              (setq tmp (ccad:add-pair-unique pairs seen c0 c1))
              (setq pairs (car tmp))
              (setq seen  (cadr tmp))
            )
          )
          (setq r (1+ r))
        )
        (setq i (1+ i))
      )
    )
  )

  ; TEXT/MTEXT 拼合兜底
  (setq textss (ssget "_X" (list (cons 0 "TEXT,MTEXT") (cons 410 layout-name))))
  (if textss
    (progn
      (setq txti 0)
      (repeat (sslength textss)
        (setq ename (ssname textss txti))
        (setq ted   (entget ename))
        (setq typ   (cdr (assoc 0 ted)))
        (if (= typ "TEXT")
          (setq txt (cdr (assoc 1 ted)))
          (setq txt (ccad:get-prop (vlax-ename->vla-object ename) 'TextString ""))
        )
        (setq line (ccad:normalize-text txt))
        (setq code (ccad:first-token line))
        (setq name (ccad:rest-token line))
        (if (and (ccad:code-like-p code) (/= name ""))
          (progn
            (setq tmp (ccad:add-pair-unique pairs seen code name))
            (setq pairs (car tmp))
            (setq seen  (cadr tmp))
          )
        )
        (setq txti (1+ txti))
      )
    )
  )

  (setq out '())
  (foreach kv (reverse pairs)
    (setq out
      (cons
        (strcat
          "{"
          "\"code\":\"" (ccad:json-escape (car kv)) "\","
          "\"name\":\"" (ccad:json-escape (cdr kv)) "\""
          "}"
        )
        out
      )
    )
  )
  (strcat "[" (ccad:join (reverse out) ",") "]")
)

; -------------------------
; 图层定义 LAYER
; -------------------------

(defun ccad:layers-json (/ doc layers out item ly name on freeze lock visible)
  (setq out '())
  (setq doc (vla-get-ActiveDocument (vlax-get-acad-object)))
  (setq layers (vla-get-Layers doc))
  (vlax-for ly layers
    (setq name   (ccad:get-prop ly 'Name ""))
    (setq on     (ccad:get-prop ly 'LayerOn T))
    (setq freeze (ccad:get-prop ly 'Freeze nil))
    (setq lock   (ccad:get-prop ly 'Lock nil))
    (setq visible (and (ccad:is-true on) (not (ccad:is-true freeze))))

    (setq item
      (strcat
        "{"
        "\"name\":\"" (ccad:json-escape name) "\","
        "\"visible\":" (ccad:bool-json visible) ","
        "\"on\":" (ccad:bool-json on) ","
        "\"frozen\":" (ccad:bool-json freeze) ","
        "\"locked\":" (ccad:bool-json lock)
        "}"
      )
    )
    (setq out (cons item out))
  )
  (strcat "[" (ccad:join (reverse out) ",") "]")
)

; -------------------------
; 写入 JSON 文件
; -------------------------

(defun ccad:write-layout-json (output-dir dwg-name layout-name / path fh
                                           viewports-json dims-json pseudo-json
                                           ins-res indexes-json title-json
                                           sheet-no sheet-name
                                           leaders-json mat-table-json layers-json)
  (setq path (strcat output-dir "\\" (ccad:safe-file dwg-name) "_" (ccad:safe-file layout-name) ".json"))

  (setq viewports-json (ccad:viewport-items-json layout-name))
  (setq dims-json      (ccad:dim-items-json layout-name))
  (setq pseudo-json    (ccad:pseudo-text-items-json layout-name))

  (setq ins-res        (ccad:index-or-title-json layout-name))
  (setq indexes-json   (nth 0 ins-res))
  (setq title-json     (nth 1 ins-res))
  (setq sheet-no       (nth 2 ins-res))
  (setq sheet-name     (nth 3 ins-res))

  (if (= sheet-no "")   (setq sheet-no (ccad:guess-sheet-no layout-name)))
  (if (= sheet-name "") (setq sheet-name (ccad:guess-sheet-name layout-name sheet-no)))

  (setq leaders-json   (ccad:leader-items-json layout-name))
  (setq mat-table-json (ccad:table-pairs-json layout-name))
  (setq layers-json    (ccad:layers-json))

  (setq fh (open path "w"))
  (if fh
    (progn
      (write-line "{" fh)
      (write-line (strcat "  \"source_dwg\": \"" (ccad:json-escape (strcat dwg-name ".dwg")) "\",") fh)
      (write-line (strcat "  \"layout_name\": \"" (ccad:json-escape layout-name) "\",") fh)
      (write-line (strcat "  \"sheet_no\": \"" (ccad:json-escape sheet-no) "\",") fh)
      (write-line (strcat "  \"sheet_name\": \"" (ccad:json-escape sheet-name) "\",") fh)
      (write-line (strcat "  \"extracted_at\": \"" (menucmd "M=$(edtime,$(getvar,date),YYYY-MM-DD HH:MM:SS)") "\",") fh)
      (write-line "  \"data_version\": 1," fh)
      (write-line "  \"scale\": \"\"," fh)
      (write-line "  \"model_range\": {\"min\": [0.0, 0.0], \"max\": [0.0, 0.0]}," fh)
      (write-line (strcat "  \"viewports\": " viewports-json ",") fh)
      (write-line (strcat "  \"dimensions\": " dims-json ",") fh)
      (write-line (strcat "  \"pseudo_texts\": " pseudo-json ",") fh)
      (write-line (strcat "  \"indexes\": " indexes-json ",") fh)
      (write-line (strcat "  \"title_blocks\": " title-json ",") fh)
      (write-line (strcat "  \"materials\": " leaders-json ",") fh)
      (write-line (strcat "  \"material_table\": " mat-table-json ",") fh)
      (write-line (strcat "  \"layers\": " layers-json) fh)
      (write-line "}" fh)
      (close fh)
    )
  )
)

(defun ccad:ensure-dir (dir /)
  (if (not (vl-file-directory-p dir))
    (vl-mkdir dir)
  )
)

(defun ccad:write-done-flag (flag-path / fh)
  (setq fh (open flag-path "w"))
  (if fh
    (progn
      (write-line "ok" fh)
      (close fh)
    )
  )
)

; -------------------------
; 对外命令
; -------------------------

(defun ccad:export-layout-json (output-dir done-flag / doc dwg-name layouts layout lname)
  (setq doc (vla-get-ActiveDocument (vlax-get-acad-object)))
  (setq dwg-name (vl-filename-base (getvar "DWGNAME")))

  (ccad:ensure-dir output-dir)
  (setvar "FILEDIA" 0)
  (setvar "CMDDIA" 0)
  (setvar "PROXYNOTICE" 0)
  (setvar "FONTALT" "txt.shx")

  (setq layouts (vla-get-Layouts doc))
  (vlax-for layout layouts
    (setq lname (vla-get-Name layout))
    (if (/= (strcase lname) "MODEL")
      (progn
        (setvar "CTAB" lname)
        (ccad:write-layout-json output-dir dwg-name lname)
      )
    )
  )

  (ccad:write-done-flag done-flag)
  (princ)
)

(defun c:CCAD_EXPORT_LAYOUT_JSON ()
  (prompt "\nCCAD_EXPORT_LAYOUT_JSON 请通过 COM 自动化调用。")
  (princ)
)

(princ)
