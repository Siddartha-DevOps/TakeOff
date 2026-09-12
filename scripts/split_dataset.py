import os, random, shutil
imgs = os.listdir('datasets/rooms_yolo/images')
random.shuffle(imgs)
n = len(imgs)
splits = {'train': imgs[:int(.7*n)], 'val': imgs[int(.7*n):int(.85*n)], 'test': imgs[int(.85*n):]}
for split, files in splits.items():
    os.makedirs(f'datasets/rooms_yolo/images/{split}', exist_ok=True)
    os.makedirs(f'datasets/rooms_yolo/labels/{split}', exist_ok=True)
    for f in files:
        shutil.move(f'datasets/rooms_yolo/images/{f}', f'datasets/rooms_yolo/images/{split}/{f}')
        lbl = f.rsplit('.', 1)[0] + '.txt'
        if os.path.exists(f'datasets/rooms_yolo/labels/{lbl}'):
            shutil.move(f'datasets/rooms_yolo/labels/{lbl}', f'datasets/rooms_yolo/labels/{split}/{lbl}')
