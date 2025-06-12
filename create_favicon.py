from PIL import Image
import os

def create_favicon():
    # 원본 이미지 로드 (logo.png 사용)
    img = Image.open('static/logo.png')
    
    # 여러 크기로 리사이즈
    sizes = [16, 32, 48]
    images = []
    
    for size in sizes:
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        images.append(resized)
    
    # 첫 번째 이미지를 기본으로 사용
    images[0].save('static/favicon.ico', 
                  format='ICO',
                  sizes=[(size, size) for size in sizes],
                  append_images=images[1:])

if __name__ == '__main__':
    create_favicon() 