import time



# 统一的请求回复必有字段
def build_common_response(business_data: dict = None, ret_code: int = 0, err_msg: str = "") -> dict:
        response = {
            "ret_code": ret_code,
            "create_time": str(int(time.time() * 1000)),
            "err_msg": err_msg,
        }
        if business_data:
            response.update(business_data)
        return response