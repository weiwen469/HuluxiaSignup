import requests

Api_Url= "api.haozhuma.com"

def login(
        user,psee
):
    url=f"https://{Api_Url}/sms/?api=login&user={user}&pass={psee}"
    x=requests.get(url)
    x=x.json()
    if x['code']==-1:
        return x['msg']
    else:
        return x['token']



#获取账号余额
def Getmoney(token):
    x=requests.get(f'https://{Api_Url}/sms/?api=getSummary&token={token}').json()
    if x['code']!=0:
        return  x['msg']
    else:
        return x['money']


#获取手机号
def getPhone(token,sid):
    base_url=f"https://{Api_Url}/sms/?api=getPhone&token={token}&sid={sid}"

    try:
        response = requests.get(base_url, timeout=10)
        response.raise_for_status()  # 检查HTTP状态码
        data = response.json()  # 解析JSON响应
        # 判断业务状态码
        if data.get("code") == "0":
            # print("成功获取手机号:", data.get("phone"))
            # print("归属地:", data.get("phone_gsd"))
            # print("运营商:", data.get("sp"))
            return data.get("phone")
            # 其他字段可按需使用
        else:
            print("失败，错误码:", data.get("code"), "描述:", data.get("msg"))

    except requests.exceptions.RequestException as e:
        print("请求异常:", e)
    except ValueError as e:
        print("解析JSON失败:", e)

#获取短信
def getMessage(token, sid, phone):
    try:
        x = requests.get(
            f"https://{Api_Url}/sms/?api=getMessage&token={token}&sid={sid}&phone={phone}",
            timeout=10,
        ).json()
        if x.get("code") == "0":
            return x.get("yzm")
        return None
    except Exception as e:
        print("异常：", e)
        return None



#释放手机号
def cancelRecv(token,sid,phone):
    x=requests.get(f"https://{Api_Url}/sms/?api=cancelRecv&token={token}&sid={sid}&phone={phone}").json()
    return x['msg']

#拉黑手机号
def addBlacklist(token,sid,phone):
    x=requests.get(f"https://{Api_Url}/sms/?api=addBlacklist&token={token}&sid={sid}&phone={phone}").json()
    return x['msg']
