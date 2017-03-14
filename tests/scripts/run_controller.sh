#!/bin/bash

nohup ryu-manager ryu.app.ofctl_rest /faucet-src/src/ryu_faucet/org/onfsdn/faucet/faucet.py --wsapi-port 8084 &
echo $! > /etc/ryu/contr_pid

nohup python /faucet-src/src/ryu_faucet/org/onfsdn/faucet/HTTPServer.py > httpserver.txt &
echo $! > /root/http_server.pid.txt
