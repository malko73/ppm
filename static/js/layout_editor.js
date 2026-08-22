/**
 * Layout Editor JavaScript - Issue #5 P1
 * 
 * State Management:
 * 
 * Persistent State (DB保存対象)
 *   textRows: [ { key, label, x, y, w, h, ... } ]  // x/y/w/h は mm
 *   imageRows: [ { key, label, x, y, w, h, ... } ] // x/y/w/h は mm
 * 
 * Ephemeral UI State (クライアント内部のみ)
 *   selectedObject: { type: 'text'|'image', key: string }
 *   zoom: number (default 100)
 *   history: EditorState[]  // Undo/Redo用
 *   historyIndex: number
 *   DOM px座標: compute-on-demand (mm → px)
 * 
 * ガード: 保存時は Persistent State のみ送信
 */

// ===== Coordinate Conversion =====

class LayoutCoordinates {
    constructor(templateWidthMm, templateHeightMm) {
        this.templateWidthMm = templateWidthMm || 210.0;
        this.templateHeightMm = templateHeightMm || 297.0;
        
        this.browserPdfWidthPx = 600;
        this.browserPdfHeightPx = 848;
        
        this.pxPerMmX = this.browserPdfWidthPx / this.templateWidthMm;
        this.pxPerMmY = this.browserPdfHeightPx / this.templateHeightMm;
    }
    
    mmToPx(mm, axis) {
        return axis === 'x' ? mm * this.pxPerMmX : mm * this.pxPerMmY;
    }
    
    pxToMm(px, axis) {
        return axis === 'x' ? px / this.pxPerMmX : px / this.pxPerMmY;
    }
    
    roundMm(value, decimals = 2) {
        return Math.round(value * Math.pow(10, decimals)) / Math.pow(10, decimals);
    }
    
    snapToGrid(mm, gridMm = 1.0) {
        return Math.round(mm / gridMm) * gridMm;
    }
}

// ===== Persistent State (DB保存対象) =====

class EditorState {
    constructor(textRows, imageRows) {
        // Deep copy: Undo/Redo用スナップショット
        this.textRows = JSON.parse(JSON.stringify(textRows || []));
        this.imageRows = JSON.parse(JSON.stringify(imageRows || []));
    }
    
    clone() {
        return new EditorState(this.textRows, this.imageRows);
    }
    
    equals(other) {
        return JSON.stringify(this) === JSON.stringify(other);
    }
    
    updateTextRow(key, updates) {
        const row = this.textRows.find(r => r.key === key);
        if (row) {
            Object.assign(row, updates);
        }
    }
    
    updateImageRow(key, updates) {
        const row = this.imageRows.find(r => r.key === key);
        if (row) {
            Object.assign(row, updates);
        }
    }
}

// ===== Global State =====

let coords;
let persistentState;           // DB保存対象
let selectedObject = null;     // Ephemeral: {type, key}
let zoom = 100;                // Ephemeral: display zoom
let history = [];              // Ephemeral: Undo/Redo
let historyIndex = -1;         // Ephemeral: 現在の履歴位置
let gridSnapEnabled = true;    // Ephemeral: Grid snap ON/OFF
let gridMm = 1.0;              // Ephemeral: Grid size (mm)

let draggingElement = null;
let resizingElement = null;
let dragStart = { x: 0, y: 0 };
let elementStart = { left: 0, top: 0, width: 0, height: 0 };

// ===== Initialization =====

document.addEventListener('DOMContentLoaded', function() {
    // Initialize coordinate system
    coords = new LayoutCoordinates(
        COORDINATE_CONFIG.TEMPLATE_WIDTH_MM,
        COORDINATE_CONFIG.TEMPLATE_HEIGHT_MM
    );
    
    // Initialize persistent state from HTML data
    persistentState = new EditorState(
        INITIAL_TEXT_LAYOUT,
        INITIAL_IMAGE_LAYOUT
    );
    
    // Initialize history
    history.push(persistentState.clone());
    historyIndex = 0;
    
    // Setup event listeners
    setupCanvasEvents();
    setupButtonEvents();
    setupKeyboardEvents();
    setupZoomControls();
    setupLayerPanel();
    setupUndoRedoButtons();
    setupAddElementButtons();
    
    // Initial render
    redrawUI();
    
    // Prevent right-click context menu on canvas
    document.getElementById('layoutCanvas').addEventListener('contextmenu', e => e.preventDefault());
});

// ===== Render: mm → px (zoom考慮) =====

function redrawUI() {
    const canvas = document.getElementById('layoutCanvas');
    
    // Clear existing elements
    canvas.querySelectorAll('.layout-element').forEach(el => el.remove());
    
    const zoomFactor = zoom / 100;
    
    // Render text elements
    persistentState.textRows.forEach(text => {
        const x_px = coords.mmToPx(text.x, 'x') * zoomFactor;
        const y_px = coords.mmToPx(text.y, 'y') * zoomFactor;
        const w_px = coords.mmToPx(text.w, 'x') * zoomFactor;
        const h_px = coords.mmToPx(text.h, 'y') * zoomFactor;
        
        const el = createLayoutElement('text', text.key, text.label, x_px, y_px, w_px, h_px);
        canvas.appendChild(el);
    });
    
    // Render image elements
    persistentState.imageRows.forEach(image => {
        const x_px = coords.mmToPx(image.x, 'x') * zoomFactor;
        const y_px = coords.mmToPx(image.y, 'y') * zoomFactor;
        const w_px = coords.mmToPx(image.w, 'x') * zoomFactor;
        const h_px = coords.mmToPx(image.h, 'y') * zoomFactor;
        
        const el = createLayoutElement('image', image.key, image.label, x_px, y_px, w_px, h_px);
        canvas.appendChild(el);
    });
    
    // Re-bind events
    setupCanvasEvents();
    
    // Update layer panel
    updateLayerPanel();
}

function createLayoutElement(type, key, label, x_px, y_px, w_px, h_px) {
    const el = document.createElement('div');
    el.className = `layout-element ${type}-element`;
    el.dataset.type = type;
    el.dataset.key = key;
    el.style.left = x_px + 'px';
    el.style.top = y_px + 'px';
    el.style.width = w_px + 'px';
    el.style.height = h_px + 'px';
    
    if (selectedObject && selectedObject.type === type && selectedObject.key === key) {
        el.classList.add('selected');
    }
    
    el.innerHTML = `
        <div class="element-label">${label}</div>
        <div class="element-border"></div>
        <div class="resize-handle resize-handle-nwse"></div>
    `;
    
    return el;
}

// ===== Canvas Event Handlers =====

function setupCanvasEvents() {
    const canvas = document.getElementById('layoutCanvas');
    const elements = canvas.querySelectorAll('.layout-element');
    
    elements.forEach(element => {
        element.addEventListener('mousedown', onElementMouseDown);
        element.addEventListener('selectstart', e => e.preventDefault());
    });
    
    document.addEventListener('mousemove', onDocumentMouseMove);
    document.addEventListener('mouseup', onDocumentMouseUp);
}

function onElementMouseDown(event) {
    event.preventDefault();
    
    const element = event.currentTarget;
    const resizeHandle = event.target.closest('.resize-handle');
    const type = element.dataset.type;
    const key = element.dataset.key;
    
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
        // Select + drag mode
        selectElement(type, key);
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
        
        // Apply zoom factor
        const zoomFactor = zoom / 100;
        
        // Convert px to mm (zoom-aware)
        const x_mm = coords.pxToMm(newLeft / zoomFactor, 'x');
        const y_mm = coords.pxToMm(newTop / zoomFactor, 'y');
        
        // Apply grid snap
        const snapped_x_mm = gridSnapEnabled ? coords.snapToGrid(x_mm, gridMm) : coords.roundMm(x_mm, 2);
        const snapped_y_mm = gridSnapEnabled ? coords.snapToGrid(y_mm, gridMm) : coords.roundMm(y_mm, 2);
        
        // Update persistent state
        const type = draggingElement.dataset.type;
        const key = draggingElement.dataset.key;
        
        if (type === 'text') {
            persistentState.updateTextRow(key, { x: snapped_x_mm, y: snapped_y_mm });
        } else {
            persistentState.updateImageRow(key, { x: snapped_x_mm, y: snapped_y_mm });
        }
        
        // Update DOM (px with current zoom)
        draggingElement.style.left = coords.mmToPx(snapped_x_mm, 'x') * zoomFactor + 'px';
        draggingElement.style.top = coords.mmToPx(snapped_y_mm, 'y') * zoomFactor + 'px';
        
        updatePropertyPanel();
    }
    
    if (resizingElement) {
        const deltaX = event.clientX - dragStart.x;
        const deltaY = event.clientY - dragStart.y;
        
        const newWidth = Math.max(40, elementStart.width + deltaX);
        const newHeight = Math.max(40, elementStart.height + deltaY);
        
        // Apply zoom factor
        const zoomFactor = zoom / 100;
        
        // Convert px to mm (zoom-aware)
        const w_mm = coords.pxToMm(newWidth / zoomFactor, 'x');
        const h_mm = coords.pxToMm(newHeight / zoomFactor, 'y');
        
        // Apply grid snap
        const snapped_w_mm = gridSnapEnabled ? coords.snapToGrid(w_mm, gridMm) : coords.roundMm(w_mm, 2);
        const snapped_h_mm = gridSnapEnabled ? coords.snapToGrid(h_mm, gridMm) : coords.roundMm(h_mm, 2);
        
        // Update persistent state
        const type = resizingElement.dataset.type;
        const key = resizingElement.dataset.key;
        
        if (type === 'text') {
            persistentState.updateTextRow(key, { w: snapped_w_mm, h: snapped_h_mm });
        } else {
            persistentState.updateImageRow(key, { w: snapped_w_mm, h: snapped_h_mm });
        }
        
        // Update DOM
        resizingElement.style.width = coords.mmToPx(snapped_w_mm, 'x') * zoomFactor + 'px';
        resizingElement.style.height = coords.mmToPx(snapped_h_mm, 'y') * zoomFactor + 'px';
        
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

// ===== Selection =====

function selectElement(type, key) {
    selectedObject = { type, key };
    redrawUI();
    updatePropertyPanel();
}

function deselectElement() {
    selectedObject = null;
    redrawUI();
    updatePropertyPanel();
}

// ===== Property Panel =====

function updatePropertyPanel() {
    if (!selectedObject) {
        document.getElementById('propertyForm').innerHTML = 
            '<p class="text-muted text-center">要素を選択してください</p>';
        document.getElementById('savePdfButton').disabled = true;
        return;
    }
    
    document.getElementById('savePdfButton').disabled = false;
    
    // Get current mm values
    const row = selectedObject.type === 'text'
        ? persistentState.textRows.find(r => r.key === selectedObject.key)
        : persistentState.imageRows.find(r => r.key === selectedObject.key);
    
    if (!row) return;
    
    let formHtml = `
        <div class="property-item">
            <h5>${row.label}</h5>
            <p class="text-muted small">
                <strong>Type:</strong> ${selectedObject.type} | <strong>Key:</strong> ${row.key}
            </p>
        </div>
        <div class="form-group">
            <label>ラベル</label>
            <input type="text" class="form-control form-control-sm" id="propLabel" value="${row.label}">
        </div>
        <div class="form-group">
            <label>X 位置 (mm)</label>
            <input type="number" class="form-control form-control-sm" id="propX" value="${row.x}" step="0.1">
        </div>
        <div class="form-group">
            <label>Y 位置 (mm)</label>
            <input type="number" class="form-control form-control-sm" id="propY" value="${row.y}" step="0.1">
        </div>
        <div class="form-group">
            <label>幅 (mm)</label>
            <input type="number" class="form-control form-control-sm" id="propW" value="${row.w}" step="0.1">
        </div>
        <div class="form-group">
            <label>高さ (mm)</label>
            <input type="number" class="form-control form-control-sm" id="propH" value="${row.h}" step="0.1">
        </div>
    `;
    
    // Add text-specific attributes
    if (selectedObject.type === 'text') {
        formHtml += `
            <hr class="my-2">
            <h6 class="text-muted">テキスト属性</h6>
            <div class="form-group">
                <label>フォントサイズ (pt)</label>
                <input type="number" class="form-control form-control-sm" id="propFontSize" value="${row.font_size || 12}" step="1" min="6" max="72">
            </div>
            <div class="form-group">
                <label>フォント</label>
                <select class="form-control form-control-sm" id="propFontFamily">
                    <option value="gothic" ${row.font_family === 'gothic' ? 'selected' : ''}>ゴシック</option>
                    <option value="mincho" ${row.font_family === 'mincho' ? 'selected' : ''}>明朝</option>
                </select>
            </div>
            <div class="form-group">
                <label>太さ</label>
                <select class="form-control form-control-sm" id="propFontWeight">
                    <option value="normal" ${row.font_weight === 'normal' ? 'selected' : ''}>通常</option>
                    <option value="bold" ${row.font_weight === 'bold' ? 'selected' : ''}>太字</option>
                </select>
            </div>
            <div class="form-group">
                <label>色</label>
                <input type="color" class="form-control form-control-sm" id="propColor" value="${row.color || '#000000'}">
            </div>
            <div class="form-group">
                <label>揃え</label>
                <select class="form-control form-control-sm" id="propTextAlign">
                    <option value="left" ${row.text_align === 'left' ? 'selected' : ''}>左</option>
                    <option value="center" ${row.text_align === 'center' ? 'selected' : ''}>中央</option>
                    <option value="right" ${row.text_align === 'right' ? 'selected' : ''}>右</option>
                </select>
            </div>
        `;
    }
    
    formHtml += `
        <button class="btn btn-sm btn-outline-primary w-100 mt-2" id="applyPropButton">
            適用
        </button>
        <button class="btn btn-sm btn-outline-danger w-100 mt-2" id="deletePropButton">
            削除
        </button>
    `;
    
    document.getElementById('propertyForm').innerHTML = formHtml;
    document.getElementById('applyPropButton').addEventListener('click', applyPropertyChanges);
    document.getElementById('deletePropButton').addEventListener('click', deleteSelectedElement);
}

function applyPropertyChanges() {
    if (!selectedObject) return;
    
    const x = parseFloat(document.getElementById('propX').value);
    const y = parseFloat(document.getElementById('propY').value);
    const w = parseFloat(document.getElementById('propW').value);
    const h = parseFloat(document.getElementById('propH').value);
    const label = document.getElementById('propLabel').value;
    
    const updates = { x, y, w, h, label };
    
    if (selectedObject.type === 'text') {
        // Add text-specific properties
        const fontSize = parseInt(document.getElementById('propFontSize').value);
        const fontFamily = document.getElementById('propFontFamily').value;
        const fontWeight = document.getElementById('propFontWeight').value;
        const color = document.getElementById('propColor').value;
        const textAlign = document.getElementById('propTextAlign').value;
        
        Object.assign(updates, {
            font_size: fontSize,
            font_family: fontFamily,
            font_weight: fontWeight,
            color: color,
            text_align: textAlign
        });
        
        persistentState.updateTextRow(selectedObject.key, updates);
    } else {
        persistentState.updateImageRow(selectedObject.key, updates);
    }
    
    pushHistory();
    redrawUI();
    updatePropertyPanel();
}

// ===== Zoom Controls =====

function setupZoomControls() {
    // Add zoom buttons to footer (if not already present)
    const zoomHtml = `
        <div class="zoom-controls ms-auto">
            <button class="btn btn-sm btn-outline-secondary" id="zoomOutBtn">
                <i class="bi bi-zoom-out"></i>
            </button>
            <span class="mx-2" id="zoomDisplay">100%</span>
            <button class="btn btn-sm btn-outline-secondary" id="zoomInBtn">
                <i class="bi bi-zoom-in"></i>
            </button>
            <button class="btn btn-sm btn-outline-secondary" id="fitScreenBtn">
                <i class="bi bi-fullscreen"></i> Fit
            </button>
        </div>
    `;
    
    const footer = document.querySelector('.layout-editor-footer');
    if (footer && !document.getElementById('zoomOutBtn')) {
        footer.insertAdjacentHTML('beforeend', zoomHtml);
        
        document.getElementById('zoomOutBtn').addEventListener('click', () => setZoom(zoom - 10));
        document.getElementById('zoomInBtn').addEventListener('click', () => setZoom(zoom + 10));
        document.getElementById('fitScreenBtn').addEventListener('click', () => fitToScreen());
    }
}

function setZoom(newZoom) {
    zoom = Math.max(50, Math.min(200, newZoom));  // Clamp 50-200%
    document.getElementById('zoomDisplay').textContent = zoom + '%';
    redrawUI();  // Persistent state は変わらない、DOM表示のみ変更
}

function fitToScreen() {
    // Calculate zoom to fit canvas in viewport
    const canvas = document.getElementById('layoutCanvas');
    const container = canvas.parentElement;
    
    const scaleX = (container.offsetWidth - 40) / 600;
    const scaleY = (container.offsetHeight - 40) / 848;
    const newZoom = Math.min(scaleX, scaleY) * 100;
    
    setZoom(Math.round(newZoom));
}

// ===== Layer Panel =====

function setupLayerPanel() {
    // Layer panel is managed by updateLayerPanel()
    const checkbox = document.getElementById('gridSnapCheckbox');
    if (checkbox) {
        checkbox.addEventListener('change', (e) => {
            gridSnapEnabled = e.target.checked;
        });
    }
}

// ===== Add Element Functions =====

function setupAddElementButtons() {
    const addTextButton = document.getElementById('addTextButton');
    const addImageButton = document.getElementById('addImageButton');
    
    if (addTextButton) {
        addTextButton.addEventListener('click', addTextElement);
    }
    
    if (addImageButton) {
        addImageButton.addEventListener('click', addImageElement);
    }
}

function generateUniqueKey(prefix, existingKeys) {
    let counter = 1;
    let key = `${prefix}_${counter}`;
    while (existingKeys.includes(key)) {
        counter++;
        key = `${prefix}_${counter}`;
    }
    return key;
}

function addTextElement() {
    const existingKeys = [
        ...persistentState.textRows.map(r => r.key),
        ...persistentState.imageRows.map(r => r.key)
    ];
    
    const newKey = generateUniqueKey('text', existingKeys);
    const newText = {
        key: newKey,
        label: `新しいテキスト ${persistentState.textRows.length + 1}`,
        x: 20.0,
        y: 20.0,
        w: 80.0,
        h: 10.0,
        font_size: 12,
        font_family: 'gothic',
        font_weight: 'normal',
        color: '#000000',
        text_align: 'left',
        writing_mode: 'horizontal-tb'
    };
    
    persistentState.textRows.push(newText);
    pushHistory();
    redrawUI();
    
    // Select the new element
    selectElement('text', newKey);
}

function addImageElement() {
    const existingKeys = [
        ...persistentState.textRows.map(r => r.key),
        ...persistentState.imageRows.map(r => r.key)
    ];
    
    const newKey = generateUniqueKey('image', existingKeys);
    const newImage = {
        key: newKey,
        label: `新しい画像 ${persistentState.imageRows.length + 1}`,
        x: 20.0,
        y: 40.0,
        w: 80.0,
        h: 60.0
    };
    
    persistentState.imageRows.push(newImage);
    pushHistory();
    redrawUI();
    
    // Select the new element
    selectElement('image', newKey);
}

function updateLayerPanel() {
    const layerPanel = document.getElementById('layerPanel');
    if (!layerPanel) return;
    
    let html = '<div class="layer-list">';
    
    // Text layers
    persistentState.textRows.forEach((text, idx) => {
        const isSelected = selectedObject && selectedObject.type === 'text' && selectedObject.key === text.key;
        const classes = `layer-item ${isSelected ? 'selected' : ''}`;
        html += `
            <div class="${classes}" data-type="text" data-key="${text.key}" style="z-index: ${1000 + idx}">
                <div class="layer-type-badge text">T</div>
                <div class="layer-name">${text.label}</div>
            </div>
        `;
    });
    
    // Image layers
    persistentState.imageRows.forEach((image, idx) => {
        const isSelected = selectedObject && selectedObject.type === 'image' && selectedObject.key === image.key;
        const classes = `layer-item ${isSelected ? 'selected' : ''}`;
        html += `
            <div class="${classes}" data-type="image" data-key="${image.key}" style="z-index: ${2000 + idx}">
                <div class="layer-type-badge image">I</div>
                <div class="layer-name">${image.label}</div>
            </div>
        `;
    });
    
    html += '</div>';
    layerPanel.innerHTML = html;
    
    // Bind layer click events
    layerPanel.querySelectorAll('.layer-item').forEach(item => {
        item.addEventListener('click', () => {
            selectElement(item.dataset.type, item.dataset.key);
        });
    });
}

// ===== Undo/Redo =====

function setupUndoRedoButtons() {
    const undoBtn = document.createElement('button');
    undoBtn.className = 'btn btn-sm btn-outline-secondary';
    undoBtn.id = 'undoBtn';
    undoBtn.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i> Undo';
    undoBtn.addEventListener('click', undo);
    
    const redoBtn = document.createElement('button');
    redoBtn.className = 'btn btn-sm btn-outline-secondary';
    redoBtn.id = 'redoBtn';
    redoBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Redo';
    redoBtn.addEventListener('click', redo);
    
    const footer = document.querySelector('.layout-editor-footer');
    footer.insertBefore(undoBtn, footer.firstChild);
    footer.insertBefore(redoBtn, footer.children[1]);
}

function pushHistory() {
    // Remove any redo history after current position
    history = history.slice(0, historyIndex + 1);
    
    // Add new state
    const newState = persistentState.clone();
    if (historyIndex >= 0 && !newState.equals(history[historyIndex])) {
        history.push(newState);
        historyIndex++;
    }
}

function undo() {
    if (historyIndex > 0) {
        historyIndex--;
        persistentState = history[historyIndex].clone();
        redrawUI();
    }
}

function redo() {
    if (historyIndex < history.length - 1) {
        historyIndex++;
        persistentState = history[historyIndex].clone();
        redrawUI();
    }
}

function deleteSelectedElement() {
    if (!selectedObject) return;
    
    const confirmed = confirm(`"${selectedObject.key}"を削除しますか？`);
    if (!confirmed) return;
    
    if (selectedObject.type === 'text') {
        persistentState.textRows = persistentState.textRows.filter(
            r => r.key !== selectedObject.key
        );
    } else if (selectedObject.type === 'image') {
        persistentState.imageRows = persistentState.imageRows.filter(
            r => r.key !== selectedObject.key
        );
    }
    
    selectedObject = null;
    pushHistory();
    redrawUI();
    updatePropertyPanel();
}

// ===== Keyboard Shortcuts =====

function setupKeyboardEvents() {
    document.addEventListener('keydown', onKeyDown);
}

function onKeyDown(event) {
    if (!selectedObject) return;
    
    const step = event.shiftKey ? 10 : 1;  // Shift: ±10mm, else: ±1mm
    const row = selectedObject.type === 'text'
        ? persistentState.textRows.find(r => r.key === selectedObject.key)
        : persistentState.imageRows.find(r => r.key === selectedObject.key);
    
    if (!row) return;
    
    switch (event.key) {
        case 'ArrowUp':
            event.preventDefault();
            row.y = Math.max(0, row.y - step);
            break;
        case 'ArrowDown':
            event.preventDefault();
            row.y = Math.min(COORDINATE_CONFIG.TEMPLATE_HEIGHT_MM, row.y + step);
            break;
        case 'ArrowLeft':
            event.preventDefault();
            row.x = Math.max(0, row.x - step);
            break;
        case 'ArrowRight':
            event.preventDefault();
            row.x = Math.min(COORDINATE_CONFIG.TEMPLATE_WIDTH_MM, row.x + step);
            break;
        case 'Delete':
        case 'Backspace':
            event.preventDefault();
            deleteSelectedElement();
            break;
        case 'z':
            if (event.ctrlKey || event.metaKey) {
                event.preventDefault();
                if (event.shiftKey) {
                    redo();
                } else {
                    undo();
                }
            }
            break;
        default:
            return;
    }
    
    pushHistory();
    redrawUI();
}

// ===== Save to Server =====

function setupButtonEvents() {
    const savePdfButton = document.getElementById('savePdfButton');
    
    savePdfButton.addEventListener('click', saveToPdf);
}

function saveToPdf() {
    // Save all elements in bulk
    const payload = {
        bulk_save: true,
        text_layout: persistentState.textRows,
        image_layout: persistentState.imageRows
    };
    
    console.log('Sending bulk save to server:', payload);
    
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
            alert(`保存成功:\n${data.message}`);
            
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
