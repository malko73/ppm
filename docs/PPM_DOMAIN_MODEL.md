# PPM Domain Model - Data Schema
**Version: 1.0** 🔍 2026-05-06  T.A.D.A.S.H.I. Triple-Audit 🎯

## 📌 Core Entities & Relationships
```
┌─────────────┐       ┌───────────────────┐
│  User      │1     N│  Project        │
│ (AUTH_USER_MODEL via accounts)│ category:text │
└─────────────┘       └────────┬────────┘
                        │participants│M2M
                        └────────┬────────┘
                                 │1  template_file:PDF
                          ┌──────┴──────┐
                          │ProjectTemplate│is_default:bool
                          │template_file:PDF│default_positions:JSON
                          └──────┬──────┘
                                 │1  
                        ┌────────┴────────┐
                        │    Page         │
                        │ order, page_num │input_data:JSON
                        │is_finalized:bool│main_image + sub_imageN
                        └────────┬────────┘
                                 │1 
                        ┌────────┴────────┐ 1:N
                        │   PageImage     │
                        │key, label       │image:ImageField
                        └─────────────────┘
```

## 📊 Entity Table
| Entity | Description | Cardinality | Core Attributes |
|--------|-------------|-------------|----------------|
| **User** | Django Custom Auth Users | M | id, username, email, ... (accounts/models.py) |
| **Project** | Client/案件/Document | 1:N | user:FK, title, category, participants:M2M |
| **ProjectTemplate** | Project内テンプレート | 1:N | name, template_file:PDF, is_default:bool, default_positions:JSON |
| **Page** | 同一案件内の1ページ | 1:1 | project:FK, order/page_number, is_finalized:bool, input_data:JSON, images (main/sub1/sub2) |
| **PageImage** | dynamic images | 1:N | page:FK, key, label, image:ImageField |

## 🚀 Business Logic Highlights
- **Template Rendering**: PDF merge via `PDFRenderService.merge_pages_bytes(project, pages, profile='preview')`
- **High-Res Export**: Zip ZIP generation via `PDFRenderService.zip_pages_bytes(project, pages)`
- **Validation Rules**:
  - Template PDF < 100MB
  - Total Page Image < 50MB (3 images per page)
  - Image < 20MB per file

## 🔐 Security / Data Integrity
- **PDF Media Validation**: `pypdf.PdfReader` → ensure valid PDF + pages count
- **Image Validation**: JPG/PNG checked for size (PyPI Pillow?)
- **File Uploads**: Django FileField → warehouse `/media/pages/` / `templates/`

## 📝 Frequently Used Methods
- `Project.template_size_mm()` → (W, H) mm
- `Page.next_order()` / `resequence()` → order/indexing
- `Project.get_default_template()` → find default ProjectTemplate

---
**💡 Domain Analysis**: PPM は Projects → Pages → (Images) 構造を持ち、テンプレートPDFをベースとしたカスタマイズ可能な文書生成システム。
画像リッチなページで構成され、非同期ZIP生成（Celery）で大容量処理に対応。
