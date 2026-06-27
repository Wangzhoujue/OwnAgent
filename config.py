# 配置文件
import os


class Config:
    def __init__(self):
        # AI模型配置
        self.api_base_url = "The_API_base_url"
        self.api_key = "Your_api_key"
        self.ai_model = "Modelname"
       
config = Config()