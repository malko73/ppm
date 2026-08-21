/**
 * Page Form Redesigned - Issue #4 P1
 * 
 * Features:
 * 1. 左右 2 ペイン (フォーム + PDFプレビュー)
 * 2. PDFプレビュー統合 (更新ボタン)
 * 3. 未保存状態検知
 * 4. 保存導線整理
 * 5. テンプレート切替簡素化
 */

// ===== State Management =====

class FormState {
    constructor() {
        this.isDirty = false;
        this.isSaving = false;
        this.lastTemplateId = null;
    }
    
    markDirty() {
        this.isDirty = true;
        updateUI();
    }
    
    markClean() {
        this.isDirty = false;
        updateUI();
    }
    
    setTemplateId(id) {
        this.lastTemplateId = id;
    }
}

let formState = new FormState();

// ===== Initialization =====

document.addEventListener('DOMContentLoaded', function() {
    setupFormChangeDetection();
    setupPDFPreviewButton();
    setupTemplateSwitcher();
    setupFormSubmit();
    
    // Store initial template ID
    const templateSelect = document.getElementById('id_project_template');
    if (templateSelect) {
        formState.setTemplateId(templateSelect.value);
    }
    
    updateUI();
});

// ===== Form Change Detection =====

function setupFormChangeDetection() {
    const form = document.getElementById('pageForm');
    if (!form) return;
    
    form.addEventListener('input', () => {
        formState.markDirty();
    });
    
    form.addEventListener('change', () => {
        formState.markDirty();
    });
    
    // Prevent dirty state when form submitted successfully
    form.addEventListener('submit', function(e) {
        // Only reset if form is valid (no errors)
        // This is handled by server response
    });
}

// ===== UI Updates =====

function updateUI() {
    const header = document.querySelector('.page-form-header');
    const unsavedIndicator = document.getElementById('unsavedIndicator');
    const saveBtn = document.getElementById('saveBtn');
    
    if (!header) return;
    
    if (formState.isDirty) {
        // Show unsaved indicator
        header.classList.add('unsaved');
        if (unsavedIndicator) {
            unsavedIndicator.style.display = 'inline-flex';
        }
        if (saveBtn) {
            saveBtn.disabled = false;
        }
    } else {
        // Hide unsaved indicator
        header.classList.remove('unsaved');
        if (unsavedIndicator) {
            unsavedIndicator.style.display = 'none';
        }
        if (saveBtn) {
            saveBtn.disabled = false;  // Always enabled
        }
    }
}

// ===== PDF Preview =====

function setupPDFPreviewButton() {
    const updateBtn = document.getElementById('updatePreviewBtn');
    if (!updateBtn) return;
    
    updateBtn.addEventListener('click', function(e) {
        e.preventDefault();
        updatePDFPreview();
    });
}

function updatePDFPreview() {
    if (!PAGE_DATA.pdfUrl) {
        console.warn('PDF URL not available');
        return;
    }
    
    const container = document.getElementById('pdfPreviewContainer');
    if (!container) return;
    
    // Show loading indicator
    container.innerHTML = '<div class="preview-placeholder"><p class="text-muted">読み込み中...</p></div>';
    
    // Fetch PDF
    fetch(PAGE_DATA.pdfUrl)
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.blob();
        })
        .then(blob => {
            const blobUrl = URL.createObjectURL(blob);
            
            // Create embed element for PDF
            const embed = document.createElement('embed');
            embed.type = 'application/pdf';
            embed.src = blobUrl;
            embed.style.width = '100%';
            embed.style.height = '600px';
            
            // Replace placeholder
            container.innerHTML = '';
            container.appendChild(embed);
        })
        .catch(error => {
            console.error('PDF preview error:', error);
            container.innerHTML = `
                <div class="preview-placeholder">
                    <p class="text-danger"><i class="bi bi-exclamation-circle"></i> PDFの読み込みに失敗しました</p>
                    <small>${error.message}</small>
                </div>
            `;
        });
}

// ===== Template Switcher =====

function setupTemplateSwitcher() {
    const templateSelect = document.getElementById('id_project_template');
    if (!templateSelect) return;
    
    templateSelect.addEventListener('change', function() {
        const newTemplateId = this.value;
        
        if (formState.isDirty) {
            const confirmed = confirm(
                'テンプレートを変更するとフォーム内容がリセットされます。\n' +
                '未保存の変更が失われます。\n\n' +
                'よろしいですか？'
            );
            
            if (!confirmed) {
                // Revert to previous template
                this.value = formState.lastTemplateId;
                return;
            }
        }
        
        // Update template and reload form
        formState.setTemplateId(newTemplateId);
        const url = new URL(window.location.href);
        url.searchParams.set('template_id', newTemplateId);
        window.location.href = url.toString();
    });
}

// ===== Form Submit =====

function setupFormSubmit() {
    const form = document.getElementById('pageForm');
    if (!form) return;
    
    const saveBtn = document.getElementById('saveBtn');
    
    form.addEventListener('submit', function(e) {
        if (formState.isSaving) {
            e.preventDefault();
            return;
        }
        
        // Allow form submission
        // Server will handle validation and redirect
    });
}

// ===== Utility =====

function getCsrfToken() {
    const name = 'csrftoken';
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// ===== Page Visibility Warning =====

window.addEventListener('beforeunload', function(e) {
    if (formState.isDirty) {
        e.preventDefault();
        e.returnValue = '';
        return '';
    }
});
