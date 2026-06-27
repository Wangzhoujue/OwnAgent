# 配置文件
import os


class Config:
    def __init__(self):
        # AI模型配置
        self.api_base_url =  "http://172.16.166.2:8900/v1"
        self.api_key = "Your_api_key"
        self.ai_model = "Modelname"
       
config = Config()