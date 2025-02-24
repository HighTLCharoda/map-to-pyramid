import os
import subprocess
import shutil
import logging
from pathlib import Path

def get_file_info(filepath: str) -> tuple:
    """Извлекает путь, имя файла и расширение"""
    path_obj = Path(filepath)
    return (
        str(path_obj.parent),
        path_obj.stem,
        path_obj.suffix[1:]
    )

def remove_directory(path: str) -> None:
    """Рекурсивно удаляет директорию"""
    if os.path.exists(path):
        logging.info(f"Удаление старой папки: {path}")
        shutil.rmtree(path)

def run_command(command: list, description: str) -> None:
    """Запускает команду с логгированием"""
    logging.info(description)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"Ошибка: {result.stderr}")
        raise RuntimeError(f"Команда {command} завершилась с ошибкой")

def ensure_alpha_channel(input_path: str) -> str:
    """Проверяет и добавляет альфа-канал при необходимости с явным PNG форматом"""
    output_path = Path(input_path).with_stem(f"{Path(input_path).stem}_alpha").with_suffix(".png")
    
    # Получаем информацию о количестве каналов
    result = subprocess.run(
        ["vipsheader", "-f", "bands", input_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Ошибка проверки каналов: {result.stderr}")
    
    bands = int(result.stdout.strip())
    if bands == 4:
        return input_path  # Альфа-канал уже есть
        
    # Добавляем альфа-канал
    logging.info("Добавление альфа-канала...")
    run_command(
        ["vips", "addalpha", input_path, str(output_path) + "[strip]"],
        "Создание изображения с альфа-каналом"
    )
    return str(output_path)

def process_tiles(output_root: str, base_z: int, shift_x: int = 0, shift_y: int = 0) -> None:
    """Сдвигает тайлы с учетом динамического смещения для уровней"""
    output_path = Path(output_root)
    
    # Удаление уровней ниже базового
    for z_dir in output_path.glob("*"):
        if z_dir.is_dir() and z_dir.name.isdigit() and int(z_dir.name) < base_z:
            logging.info(f"Удаление уровня {z_dir.name} (z < {base_z})")
            shutil.rmtree(z_dir)
    
    # Обработка оставшихся уровней
    for z_dir in output_path.iterdir():
        if not z_dir.is_dir() or not z_dir.name.isdigit():
            continue
        
        z = int(z_dir.name)
        base_offset = -(2 ** z // 2)  # Базовое центрирование
        
        # Динамический сдвиг: shift * 2^(z - base_z)
        shift_factor = 2 ** (z - base_z)
        dynamic_shift_x = shift_x * shift_factor
        dynamic_shift_y = shift_y * shift_factor
        
        final_offset_x = base_offset + dynamic_shift_x
        final_offset_y = base_offset + dynamic_shift_y
        
        # Обработка папок X
        x_dirs = sorted([x for x in z_dir.iterdir() if x.is_dir() and x.name.isdigit()], 
                        key=lambda x: int(x.name))
        
        # Переименование с проверкой конфликтов
        for x_dir in x_dirs:
            original_x = int(x_dir.name)
            new_x = original_x + final_offset_x
            new_x_path = x_dir.parent / str(new_x)
            
            if new_x_path.exists():
                logging.warning(f"Конфликт: {new_x_path} уже существует. Пропуск.")
                continue
                
            x_dir.rename(new_x_path)
        
        # Обработка файлов Y
        for x_dir in z_dir.iterdir():
            if not x_dir.is_dir():
                continue
            
            y_files = sorted([y for y in x_dir.iterdir() if y.is_file() and y.suffix == ".webp" and y.stem.isdigit()], 
                             key=lambda y: int(y.stem))
            
            for y_file in y_files:
                original_y = int(y_file.stem)
                new_y = original_y + final_offset_y
                new_y_path = y_file.parent / f"{new_y}.webp"
                
                if new_y_path.exists():
                    logging.warning(f"Конфликт: {new_y_path} уже существует. Пропуск.")
                    continue
                    
                y_file.rename(new_y_path)

def main():
    try:
        # Получение входных данных
        input_path = input("Перетащите файл изображения сюда: ").strip('"')
        base_path, name, ext = get_file_info(input_path)
        
        # Проверка и добавление альфа-канала
        processed_input = ensure_alpha_channel(input_path)
        temp_input = processed_input != input_path
        
        # Запрос начального уровня
        # Запрос начального уровня (ИЗМЕНЕННЫЙ БЛОК)
        base_z_input = input(
            "Введите начальный уровень (z ≥ 0, пусто = 0). Все уровни ниже будут удалены:\n"
            "Пример: 3 → сохранит уровни 3,4,5...\n> "
        ).strip()
        
        base_z = 0  # Значение по умолчанию
        if base_z_input:
            base_z = int(base_z_input)
            if base_z < 0:
                raise ValueError("Уровень не может быть отрицательным")

        # Запрос сдвига
        shift_input = input(
            "Введите сдвиг X Y через пробел (пусто = центрирование):\n"
            "Примеры:\n"
            "  (пусто) → автоцентрирование\n"
            "  2 3 → сдвиг уровня BASE_Z на 2 тайла вправо, 3 вниз\n> "
        ).strip()
        
        shift_x, shift_y = 0, 0
        if shift_input:
            try:
                parts = list(map(int, shift_input.split()))
                shift_x, shift_y = parts[0], parts[1]
            except:
                raise ValueError("Некорректный формат сдвига")

        # Настройка логгирования
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        log_path = Path(base_path) / "maptotiles.log"
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
        
        # Инициализация путей
        output_root = Path(base_path) / name
        rescaled_path = Path(base_path) / f"{name}_4x.png"

        # Очистка предыдущих результатов
        remove_directory(output_root)

        # Увеличение изображения
        run_command(
            ["vips.exe", "resize", processed_input, str(rescaled_path), "4", "--kernel", "nearest"],
            "Увеличение изображения..."
        )
        
        run_command([
            "vips.exe", "dzsave", str(rescaled_path), str(output_root),
            "--suffix", ".webp[Q=90]",
            "--centre",
            "--layout", "google",
            "--background", "0",
            "--tile-size", "512"
        ], "Нарезка тайлов...")

        # Применение сдвига и очистка уровней
        process_tiles(str(output_root), base_z, shift_x, shift_y)

    except Exception as e:
        logging.critical(f"Критическая ошибка: {str(e)}")
    finally:
        # Удаление временных файлов
        if 'rescaled_path' in locals() and rescaled_path.exists():
            logging.info("Удаление увеличенного изображения...")
            os.remove(rescaled_path)
        if temp_input and Path(processed_input).exists():
            logging.info("Удаление временного файла с альфа-каналом...")
            os.remove(processed_input)

if __name__ == "__main__":
    main()