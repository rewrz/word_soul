import os
import secrets
import subprocess
import sys

def run_command(command):
    """运行一个shell命令并返回其输出"""
    try:
        print(f"正在执行: {' '.join(command)}")
        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        return True
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {' '.join(command)}")
        print(f"错误信息:\n{e.stderr}")
        return False
    except FileNotFoundError:
        print(f"错误: 找不到命令 '{command[0]}'. 请确保 flask 已安装并位于您的PATH中。")
        return False

def setup_environment():
    """配置项目的运行环境"""
    env_file = '.env'
    if not os.path.exists(env_file):
        print(f"未找到 .env 文件，正在创建...")
        secret_key = secrets.token_hex(32)
        jwt_secret_key = secrets.token_hex(32)
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(f"SECRET_KEY='{secret_key}'\n")
            f.write(f"JWT_SECRET_KEY='{jwt_secret_key}'\n")
        print("已成功生成并写入 SECRET_KEY 和 JWT_SECRET_KEY。")
    else:
        print(".env 文件已存在，将跳过密钥生成。")

    print("\n正在初始化或更新数据库...")
    if run_command(['flask', 'db', 'upgrade']):
        print("数据库配置成功！")
    else:
        print("\n数据库配置失败。请检查上面的错误信息。")
        sys.exit(1)

if __name__ == '__main__':
    print("--- 开始配置《言灵》项目 ---")
    setup_environment()
    print("\n--- 项目配置完成！---")
    print("现在您可以运行 'flask run' 来启动应用了。")