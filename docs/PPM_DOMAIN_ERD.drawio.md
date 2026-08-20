# PPM Domain ER Diagram - DrawIO Flavor
**Title: PPM_Core_Schema**
drawio:diagram
drawio:version:16.2.5

```mermaid
classDiagram
    %% PPM ERD - CustomUser 側は accountsモデル外のため記載省略
    class Project {
        +id: PK
        +user_id: FK(CustomUser)
        +title: String
        +category: String
        +description: Text
        +template_file: File(PDF)
        +default_positions: JSON
        +created_at: DateTime
        +updated_at: DateTime
        +__str__() title
    }
    
    class ProjectTemplate {
        +id: PK
        +project_id: FK(Project)
        +name: String
        +template_file: File(PDF)
        +default_positions: JSON
        +is_default: Boolean
        +created_at: DateTime
        +updated_at: DateTime
        +__str__() joined project_name
    }
    
    class Page {
        +id: PK
        +project_id: FK(Project)
        +project_template_id: FK(ProjectTemplate)
        +order: Integer(UQ within project)
        +page_number: Integer
        +page_name: String
        +is_finalized: Boolean
        +input_data: JSON
        +main_image: Image
        +sub_image1: Image
        +sub_image2: Image
        +created_at: DateTime
        +updated_at: DateTime
        +__str__() page_name
    }
    
    class PageImage {
        +id: PK
        +page_id: FK(Page)
        +key: String(UQ)
        +label: String
        +image: Image
        +created_at: DateTime
        +updated_at: DateTime
        +__str__() page.key
        +unique_together (page, key)
    }

    class CustomUser {
        <<external>>
        +id: PK
    }

    Project "1" --o "M" ProjectTemplate : has template
    Project "1" --o "N" Page : has page
    ProjectTemplate "1" --o "N" Page : uses
    Page "1" --o "N" PageImage : embeds
    Project "N" --o "N" CustomUser : participants
```
```
Note: DrawIO Flavor用PPM ERD
- BOX型: Class Model
- DIAMOND: Relationship
- CROWS FOOT: Cardinality (1:N, N:M)
```
