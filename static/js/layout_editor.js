/**
 * Layout Editor JavaScript
 * Issue #5 P0 Vertical Slice
 * 
 * Responsibility:
 * 1. Display template PDF with overlay elements
 * 2. Handle drag/resize operations
 * 3. Convert px coordinates to mm (source of truth)
 * 4. Send mm values to server via POST
 * 5. Update properties panel
 */

// ===== Coordinate Conversion =====

class LayoutCoordinates {
    constructor(templateWidthMm, templateHeightMm) {
        this.templateWidthMm = templateWidthMm || 210.0;
        this.templateHeightMm = templateHeightMm || 297.0;
        
        // Fixed browser display size
        this.browserPdfWidthPx = 600;
        this.browserPdfHeightPx = 848;
        
        // Calculate scale factors
        this.pxPerMmX = this.browserPdfWidthPx / this.templateWidthMm;
        this.pxPerMmY = this.browserPdfHeightPx / this.templateHeightMm;
    }
    
    mmToPx(mm, axis) {
        if (axis === 'x') {
            return mm * this.pxPerMmX;
        } else {
            return mm * this.pxPerMmY;
        }
    }
    
    pxToMm(px, axis) {
        if (axis === 'x') {
            return px / this.pxPerMmX;
        } else {
            return px / this.pxPerMmY;
        }
    }
    
    roundMm(value, decimals = 2) {
        return Math.round(value * Math.pow(10, decimals)) / Math.pow(10, decimals);
    }
}

// ===== Global State =====

let coords;
let selectedElement = null;
let draggingElement = null;
let resizingElement = null;
let dragStart = { x: 0, y: 0 };
let elementStart = { left: 0, top: 0, width: 0, height: 0 };
let hasChanges = false;

// ===== Initialization =====

document.addEventListener('DOMContentLoaded', function() {
    // Initialize coordinate system
    coords = new LayoutCoordinates(
        COORDINATE_CONFIG.TEMPLATE_WIDTH_MM,
        COORDINATE_CONFIG.TEMPLATE_HEIGHT_MM
    );
    
    // Setup event listeners
    setupCanvasEvents();
    setupButtonEvents();
    
    // Prevent right-click context menu on canvas
    document.getElementById('layoutCanvas').addEventListener('contextmenu', e => e.preventDefault());
});

// ===== Canvas Event Handlers =====

function setupCanvasEvents() {
    const canvas = document.getElementById('layoutCanvas');
    const elements = canvas.querySelectorAll('.layout-element');
    
    elements.forEach(element => {
        // Selection
        element.addEventListener('mousedown', onElementMouseDown);
        
        // Prevent text selection during drag
        element.addEventListener('selectstart', e => e.preventDefault());
    });
    
    // Document-level drag/resize
    document.addEventListener('mousemove', onDocumentMouseMove);
    document.addEventListener('mouseup', onDocumentMouseUp);
}

function onElementMouseDown(event) {
    event.preventDefault();
    
    const element = event.currentTarget;
    const resizeHandle = event.target.closest('.resize-handle');
    
    if (resizeHandle) {
        // Resize mode
        resizingElement = element;
        dragStart = { x: event.clientX, y: event.clientY };
        elementStart = {
            left: element.offsetLeft,
            top: element.offsetTop,
            width: element.offsetWidth,
            height: element.offsetHeight
        };
        
        element.classList.add('resizing');
    } else {
        // Drag mode
        selectElement(element);
        draggingElement = element;
        dragStart = { x: event.clientX, y: event.clientY };
        elementStart = {
            left: element.offsetLeft,
            top: element.offsetTop
        };
        
        element.classList.add('dragging');
    }
}

function onDocumentMouseMove(event) {
    if (draggingElement) {
        const deltaX = event.clientX - dragStart.x;
        const deltaY = event.clientY - dragStart.y;
        
        const newLeft = elementStart.left + deltaX;
        const newTop = elementStart.top + deltaY;
        
        draggingElement.style.left = Math.max(0, newLeft) + 'px';
        draggingElement.style.top = Math.max(0, newTop) + 'px';
        
        // Constraint to canvas
        const canvas = document.getElementById('layoutCanvas');
        const maxLeft = Math.max(0, canvas.offsetWidth - draggingElement.offsetWidth);
        const maxTop = Math.max(0, canvas.offsetHeight - draggingElement.offsetHeight);
        
        if (newLeft < 0) draggingElement.style.left = '0px';
        if (newTop < 0) draggingElement.style.top = '0px';
        if (newLeft > maxLeft) draggingElement.style.left = maxLeft + 'px';
        if (newTop > maxTop) draggingElement.style.top = maxTop + 'px';
        
        hasChanges = true;
        updatePropertyPanel();
    }
    
    if (resizingElement) {
        const deltaX = event.clientX - dragStart.x;
        const deltaY = event.clientY - dragStart.y;
        
        const newWidth = Math.max(40, elementStart.width + deltaX);
        const newHeight = Math.max(40, elementStart.height + deltaY);
        
        resizingElement.style.width = newWidth + 'px';
        resizingElement.style.height = newHeight + 'px';
        
        hasChanges = true;
        updatePropertyPanel();
    }
}

function onDocumentMouseUp(event) {
    if (draggingElement) {
        draggingElement.classList.remove('dragging');
        draggingElement = null;
    }
    
    if (resizingElement) {
        resizingElement.classList.remove('resizing');
        resizingElement = null;
    }
}

// ===== Element Selection =====

function selectElement(element) {
    // Deselect previous
    if (selectedElement) {
        selectedElement.classList.remove('selected');
    }
    
    selectedElement = element;
    element.classList.add('selected');
    updatePropertyPanel();
}

// ===== Property Panel Update =====

function updatePropertyPanel() {
    if (!selectedElement) {
        document.getElementById('propertyForm').innerHTML = 
            '<p class="text-muted text-center">要素を選択してください</p>';
        document.getElementById('savePdfButton').disabled = true;
        return;
    }
    
    document.getElementById('savePdfButton').disabled = false;
    
    // Get current px values
    const pxLeft = selectedElement.offsetLeft;
    const pxTop = selectedElement.offsetTop;
    const pxWidth = selectedElement.offsetWidth;
    const pxHeight = selectedElement.offsetHeight;
    
    // Convert to mm (source of truth)
    const xMm = coords.roundMm(coords.pxToMm(pxLeft, 'x'));
    const yMm = coords.roundMm(coords.pxToMm(pxTop, 'y'));
    const wMm = coords.roundMm(coords.pxToMm(pxWidth, 'x'));
    const hMm = coords.roundMm(coords.pxToMm(pxHeight, 'y'));
    
    // Get element info
    const elementType = selectedElement.dataset.type;
    const elementKey = selectedElement.dataset.key;
    const elementLabel = selectedElement.querySelector('.element-label').textContent;
    
    // Build property form
    const formHtml = `
        <div class="property-item">
            <h5>${elementLabel}</h5>
            <p class="text-muted small">
                <strong>Type:</strong> ${elementType} | <strong>Key:</strong> ${elementKey}
            </p>
        </div>
        <div class="form-group">
            <label>X 位置 (mm)</label>
            <input type="number" class="form-control form-control-sm" id="propX" value="${xMm}" step="0.1">
        </div>
        <div class="form-group">
            <label>Y 位置 (mm)</label>
            <input type="number" class="form-control form-control-sm" id="propY" value="${yMm}" step="0.1">
        </div>
        <div class="form-group">
            <label>幅 (mm)</label>
            <input type="number" class="form-control form-control-sm" id="propW" value="${wMm}" step="0.1">
        </div>
        <div class="form-group">
            <label>高さ (mm)</label>
            <input type="number" class="form-control form-control-sm" id="propH" value="${hMm}" step="0.1">
        </div>
        <button class="btn btn-sm btn-outline-primary w-100 mt-2" id="applyPropButton">
            適用
        </button>
    `;
    
    document.getElementById('propertyForm').innerHTML = formHtml;
    
    // Bind property apply button
    document.getElementById('applyPropButton').addEventListener('click', applyPropertyChanges);
}

function applyPropertyChanges() {
    if (!selectedElement) return;
    
    const xMm = parseFloat(document.getElementById('propX').value);
    const yMm = parseFloat(document.getElementById('propY').value);
    const wMm = parseFloat(document.getElementById('propW').value);
    const hMm = parseFloat(document.getElementById('propH').value);
    
    // Convert mm back to px and apply
    const pxLeft = coords.mmToPx(xMm, 'x');
    const pxTop = coords.mmToPx(yMm, 'y');
    const pxWidth = coords.mmToPx(wMm, 'x');
    const pxHeight = coords.mmToPx(hMm, 'y');
    
    selectedElement.style.left = pxLeft + 'px';
    selectedElement.style.top = pxTop + 'px';
    selectedElement.style.width = pxWidth + 'px';
    selectedElement.style.height = pxHeight + 'px';
    
    hasChanges = true;
    updatePropertyPanel();
}

// ===== Save to Server =====

function setupButtonEvents() {
    const savePdfButton = document.getElementById('savePdfButton');
    
    savePdfButton.addEventListener('click', saveToPdf);
}

function saveToPdf() {
    if (!selectedElement) {
        alert('要素を選択してください');
        return;
    }
    
    // Get current mm values from selected element
    const pxLeft = selectedElement.offsetLeft;
    const pxTop = selectedElement.offsetTop;
    const pxWidth = selectedElement.offsetWidth;
    const pxHeight = selectedElement.offsetHeight;
    
    const xMm = coords.roundMm(coords.pxToMm(pxLeft, 'x'));
    const yMm = coords.roundMm(coords.pxToMm(pxTop, 'y'));
    const wMm = coords.roundMm(coords.pxToMm(pxWidth, 'x'));
    const hMm = coords.roundMm(coords.pxToMm(pxHeight, 'y'));
    
    const elementType = selectedElement.dataset.type;
    const elementKey = selectedElement.dataset.key;
    
    // Send POST to server
    const payload = {
        type: elementType,
        key: elementKey,
        x: xMm,
        y: yMm,
        w: wMm,
        h: hMm
    };
    
    console.log('Sending to server:', payload);
    
    fetch(SERVER_DATA.LAYOUT_EDITOR_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            alert(`保存成功:\n${data.message}\n\n保存値 (mm):\nX=${data.saved_data.x_mm}, Y=${data.saved_data.y_mm}\nW=${data.saved_data.w_mm}, H=${data.saved_data.h_mm}`);
            
            // Save reference mm values to dataset
            selectedElement.dataset.x = data.saved_data.x_mm;
            selectedElement.dataset.y = data.saved_data.y_mm;
            selectedElement.dataset.w = data.saved_data.w_mm;
            selectedElement.dataset.h = data.saved_data.h_mm;
            
            // Redirect to PDF preview after 1 second
            setTimeout(() => {
                window.open(SERVER_DATA.PROJECT_PDF_URL, '_blank');
            }, 1000);
        } else {
            alert(`エラー: ${data.message}`);
        }
    })
    .catch(error => {
        console.error('Save error:', error);
        alert(`通信エラー: ${error.message}`);
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
