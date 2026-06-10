import pyperclip
import json
import os
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import io
import base64
import webview

SAVE_DIR = "saves"
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

DOTS_W = 62
DOTS_H = 60

class Api:
    def close_app(self):
        """Closes the frameless window."""
        webview.active_window().destroy()
        
    def minimize_app(self):
        """Minimizes the frameless window."""
        webview.active_window().minimize()

    def load_latest_autosave(self):
        """
        Checks for an existing autosave file on startup.
        Returns the grid data if found, or None if starting fresh.
        """
        try:
            filepath = os.path.join(SAVE_DIR, "autosave_braille.json")
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    grid_data = json.load(f)
                return grid_data
            return None
        except Exception as e:
            print(f"Error loading autosave: {e}")
            return None

    def process_cropped_image(self, image_base64_data, pct_left, pct_top, pct_width, pct_height, mode="auto", threshold_val=128, edge_strength=0):
        try:
            header, encoded = image_base64_data.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            img = Image.open(io.BytesIO(image_bytes)).convert("L")
            
            img_w, img_h = img.size
            
            x0 = int(img_w * (pct_left / 100))
            y0 = int(img_h * (pct_top / 100))
            x1 = int(x0 + (img_w * (pct_width / 100)))
            y1 = int(y0 + (img_h * (pct_height / 100)))
            
            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(img_w, x1)
            y1 = min(img_h, y1)
            
            img_cropped = img.crop((x0, y0, x1, y1))
            img_resized = img_cropped.resize((DOTS_W, DOTS_H), Image.Resampling.LANCZOS)
            
            if edge_strength > 0:
                edges = img_resized.filter(ImageFilter.FIND_EDGES)
                edges = ImageEnhance.Brightness(edges).enhance(edge_strength / 10)
                img_resized = Image.blend(img_resized, edges, 0.5)

            img_np = np.array(img_resized)
            
            if mode == "auto":
                high_pixels = img_np[img_np > 10]
                calculated_threshold = int(np.mean(high_pixels)) if high_pixels.size > 0 else 128
            else:
                calculated_threshold = threshold_val
                
            grid_data = []
            for y in range(DOTS_H):
                row = []
                for x in range(DOTS_W):
                    sample_y = y
                    sample_x = x
                    
                    if y == 0: sample_y = 1
                    elif y == DOTS_H - 1: sample_y = DOTS_H - 2
                        
                    if x == 0: sample_x = 1
                    elif x == DOTS_W - 1: sample_x = DOTS_W - 2

                    pixel_val = img_np[sample_y, sample_x]
                    row.append(bool(pixel_val < calculated_threshold))
                grid_data.append(row)
                
            return {"status": "success", "grid": grid_data, "auto_thresh": calculated_threshold}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def compile_grid_to_string(self, grid_data):
        """
        Transforms the 2D logic grid into a Braille string matrix.
        Uses a floating remainder accumulator to carry fractional space deficits 
        across the line, eliminating sudden rounding jumps.
        """
        output_rows = []
        
        SCALE_ACTIVE = 1.0
        SCALE_BLANK = 0.83  

        LOSS_PER_BLANK = SCALE_ACTIVE - SCALE_BLANK  

        for y in range(0, len(grid_data), 4):
            raw_offsets = []
            
            for x in range(0, len(grid_data[0]), 2):
                d1 = grid_data[y][x]     if y < len(grid_data) else False
                d2 = grid_data[y+1][x]   if (y+1) < len(grid_data) else False
                d3 = grid_data[y+2][x]   if (y+2) < len(grid_data) else False
                d4 = grid_data[y][x+1]   if (y<len(grid_data) and (x+1)<len(grid_data[0])) else False
                d5 = grid_data[y+1][x+1] if ((y+1)<len(grid_data) and (x+1)<len(grid_data[0])) else False
                d6 = grid_data[y+2][x+1] if ((y+2)<len(grid_data) and (x+1)<len(grid_data[0])) else False
                d7 = grid_data[y+3][x]   if (y+3) < len(grid_data) else False
                d8 = grid_data[y+3][x+1] if ((y+3)<len(grid_data) and (x+1)<len(grid_data[0])) else False
                
                braille_offset = 0
                if d1: braille_offset |= 0x01
                if d2: braille_offset |= 0x02
                if d3: braille_offset |= 0x04
                if d4: braille_offset |= 0x08
                if d5: braille_offset |= 0x10
                if d6: braille_offset |= 0x20
                if d7: braille_offset |= 0x40
                if d8: braille_offset |= 0x80
                
                raw_offsets.append(braille_offset)

            final_line_chars = []
            i = 0
            row_length = len(raw_offsets)
            
            floating_deficit_pool = 0.0
            
            while i < row_length:
                if raw_offsets[i] == 0:
                    blank_run_start = i
                    while i < row_length and raw_offsets[i] == 0:
                        i += 1
                    blank_run_length = i - blank_run_start
                    
                    for _ in range(blank_run_length):
                        final_line_chars.append(chr(0x2800))
                    
                    floating_deficit_pool += (blank_run_length * LOSS_PER_BLANK)
                    extra_blanks_needed = int(floating_deficit_pool // SCALE_BLANK)
                    
                    for _ in range(extra_blanks_needed):
                        final_line_chars.append(chr(0x2800))
                        
                    floating_deficit_pool -= (extra_blanks_needed * SCALE_BLANK)
                else:
                    final_line_chars.append(chr(0x2800 + raw_offsets[i]))
                    i += 1
                    
            output_rows.append("".join(final_line_chars))
            
        return "\n".join(output_rows)

    def copy_text_art(self, grid_data):
        compiled_str = self.compile_grid_to_string(grid_data)
        pyperclip.copy(compiled_str)
        return True

    def auto_save_art(self, filename, grid_data):
        try:
            filepath = os.path.join(SAVE_DIR, f"{filename}.json")
            with open(filepath, "w") as f:
                json.dump(grid_data, f, indent=4)
            return True
        except:
            return False

if __name__ == '__main__':
    api = Api()
    
    webview.create_window(
        'Braille Core', 
        'web/index.html', 
        frameless=False,
        easy_drag=True,
        resizable=False,
        width=1200,
        height=800,
        js_api=api
    )
    
    webview.start(icon='web/icon_32.ico')
