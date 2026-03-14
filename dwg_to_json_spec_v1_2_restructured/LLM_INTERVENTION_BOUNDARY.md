# 41 LLM Intervention Boundary

## 41.1 Principle
LLM is not the system's raw CAD parser and must not serve as the primary decision-maker over Raw DWG JSON.

LLM should intervene only after structured evidence has been formed, but ambiguity, weak cross-sheet linkage, normalization problems, or professional expression needs still remain.

In this system, the preferred pipeline is:

```text
Page / Layout Layer
    ↓
LogicalSheet / ReviewView
    ↓
Program Semantic Extraction Pipeline
    - geometry sanitization
    - text / mtext / attrib normalization
    - block semantic mapping
    - dimension evidence extraction
    - candidate object generation
    - candidate relation generation
    ↓
LLM Disambiguation / Normalization
    ↓
Rule Engine
    ↓
LLM Review Writing / QA
```

The core principle is:

> LLM is best used for the parts that remain ambiguous **after structure has been formed**, not as a replacement for CAD parsing or the semantic extraction pipeline itself.

---

## 41.2 MUST NOT
The system must prohibit the following behaviors:

1. **Do not feed Raw CAD JSON directly to the LLM as the primary basis for review decisions.**
2. **Do not let the LLM determine cross-sheet relationships before Layout / ReviewView / LogicalSheet are established.**
3. **Do not let the LLM judge dimension compliance before `display_value`, `measured_value`, and `computed_value` are distinguished.**
4. **Do not let the LLM output high-confidence conclusions when XREF status, dynamic block degradation, text corruption, low-confidence objects, or viewport ambiguity have not been made explicit.**
5. **Do not generate high-severity issues from free-form LLM judgment without structured evidence and source references.**
6. **Do not ask the LLM to replace geometry sanitization, coordinate transforms, or deterministic extraction steps.**
7. **Do not use the LLM as a substitute for candidate generation.** It should rank or normalize candidates produced by the program pipeline, not invent them from scratch when evidence is missing.

---

## 41.3 SHOULD
The system should prefer using the LLM in the following stages.

### 41.3.1 Weak assistance after page-level structure is available
After page enumeration, metadata extraction, drawing index detection, LogicalSheet construction, and ReviewView construction, the LLM may assist with:

- title normalization
- drawing index structuring
- page-type re-checking
- ambiguous sheet naming cleanup
- weak support for one-page-multi-view interpretation

At this stage, the LLM is a **weak enhancer**, not the main structural parser.

### 41.3.2 Disambiguation after program semantic extraction
After the program pipeline has already produced candidate objects, candidate relations, dimension evidence, and ambiguity flags, the LLM may assist with:

- non-standard node/detail callout normalization
- weak relation ranking
- explanation of low-confidence linkage
- material/detail/elevation candidate disambiguation
- noisy annotation normalization

This is the **primary intervention point** for the LLM.

### 41.3.3 Professional expression after rule evaluation
After issues and evidence have already been produced, the LLM may assist with:

- review comment writing
- risk explanation
- rectification suggestions
- report summaries
- interactive Q&A

This is the **most stable and lowest-risk intervention point**.

---

## 41.4 Program-First Principle
The following tasks should be handled by the parser, rule engine, geometry logic, or deterministic program modules before considering LLM intervention:

- geometry sanitization
- coordinate transform and viewport mapping
- block / attrib extraction
- text / mtext / attrib normalization
- layer / layout / viewport state resolution
- dimension evidence extraction
- candidate object generation
- candidate relation generation
- deterministic rule evaluation
- evidence trace construction

LLM should consume the outputs of these stages, not replace them.

---

## 41.5 Standard High-Frequency Case for LLM Intervention
A common and important case is the normalization of highly inconsistent detail/node callout expressions.

Examples include:

- `3/A601`
- `3 / A-601`
- `A-601 第3节点`
- `详见 A6-01`
- `见详图 3`
- `做法详 A601-3`
- `节点 03 见 A-601`

These are not purely OCR problems and not purely regex problems. They are cases where the **same design intent is expressed in inconsistent syntax**.

### Preferred handling pattern
#### Program first
The program should first:
- tokenize the expression
- extract possible sheet identifiers
- extract possible detail/node identifiers
- narrow the search range using the drawing register
- construct one or more candidate bindings

#### Then LLM
The LLM should then:
- normalize non-standard phrasing
- rank candidate bindings
- explain why a candidate is more plausible
- mark low-confidence outcomes explicitly

So the correct pattern is:

> The LLM should not directly decide a binding from free text alone. It should normalize and rank candidates that the program pipeline has already produced.

---

## 41.6 LLM Input Constraints
LLM input should be a **ContextSlice**, not full raw project data.

Each ContextSlice should contain only the minimum relevant structured context needed for one task, ideally including:

- semantic objects
- evidence objects
- source entity IDs
- source page / review view / logical sheet identifiers
- confidence values
- ambiguity flags
- candidate relations
- relevant title / annotation / drawing register snippets

ContextSlice should avoid:

- full-document raw entity dumps
- unrelated pages
- unrelated layouts
- low-level geometry noise not relevant to the current judgment

---

## 41.7 Confidence Propagation Constraint
The confidence of any semantic conclusion must not exceed the upper bound implied by its weakest critical evidence.

Examples of low-confidence or degraded evidence include:

- missing XREF
- failed dynamic block resolution
- OCR fallback with uncertain text
- broken or noisy geometry requiring heavy sanitization
- ambiguous viewport/page mapping
- partially parsed table structure

When such degraded evidence exists, the LLM may still assist, but the final output must preserve that uncertainty.

---

## 41.8 High-Severity Issue Constraint
High-severity issues must not be produced solely from free-form LLM judgment.

A high-severity issue should satisfy at least one of the following:

1. it is triggered by a deterministic rule;
2. it is clearly supported by structured evidence;
3. it is routed into a human review queue rather than emitted as a final autonomous conclusion.

The system should not allow the LLM to create a high-severity issue without traceable evidence.

---

## 41.9 Recommended Intervention Timeline by System Stage
### Phase 2A
Preferred LLM role:
- page-type re-checking
- title normalization
- drawing index structure assistance

Do **not** use the LLM yet for full semantic object judgment.

### Phase 2B
Preferred LLM role:
- weak assistance on ReviewView / LogicalSheet ambiguity
- non-standard sheet/title normalization
- weak support for one-page-multi-view interpretation

Do **not** use the LLM yet as the main dimension or rule engine.

### Phase 2C
Preferred LLM role:
- dimension evidence explanation
- annotation normalization
- candidate callout binding ranking

### Rule / Reporting stage
Preferred LLM role:
- issue writing
- professional explanation
- report generation
- interactive Q&A

---

## 41.10 Summary
The most important practical rule is:

> LLM is best at handling what remains ambiguous after structured extraction, not at replacing CAD parsing, coordinate logic, semantic extraction, or deterministic review rules.

This boundary should be treated as a permanent development principle for the project.
