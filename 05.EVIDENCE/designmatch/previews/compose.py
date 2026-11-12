from pathlib import Path
from PIL import Image
root = Path('05.EVIDENCE/designmatch/previews')
for name in ('home', 'canvas'):
    for size in ('1920x1032', '1366x768', '1009x940'):
        design = Image.open(root / f'{name}-design-{size}.png').convert('RGB')
        app = Image.open(root / f'{name}-app-{size}.png').convert('RGB')
        assert design.size == app.size == tuple(map(int, size.split('x')))
        pair = Image.new('RGB', (design.width * 2, design.height))
        pair.paste(design, (0, 0))
        pair.paste(app, (design.width, 0))
        pair.save(root / f'{name}-pair-{size}.png')
        print(root / f'{name}-pair-{size}.png')
