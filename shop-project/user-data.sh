#!/bin/bash
# Launch Template user data (Amazon Linux 2023). Edit the 7 values below first.
exec > >(tee /var/log/shop-setup.log) 2>&1
BUCKET="shop-product-images-yourname"
ADMIN_PASSWORD="ChangeMe-123"
SECRET_KEY="put-a-long-random-string-here"      # must be the SAME for every instance
DB_HOST="your-rds-endpoint.ap-south-1.rds.amazonaws.com"
DB_USER="admin"
DB_PASS="your-db-password"
DB_NAME="shopdb"

dnf install -y httpd python3-pip
pip3 install flask gunicorn pymysql cryptography

TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
AZ=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/availability-zone)

mkdir -p /opt/shop /var/www/html/images
aws s3 cp "s3://${BUCKET}/site/index.html" /var/www/html/index.html
aws s3 cp "s3://${BUCKET}/site/admin.html" /var/www/html/admin.html
aws s3 cp "s3://${BUCKET}/site/app.py" /opt/shop/app.py
aws s3 sync "s3://${BUCKET}/images/" /var/www/html/images/
echo "${ID},${AZ}" > /var/www/html/instance.txt
echo "OK" > /var/www/html/health

cat > /etc/systemd/system/shop-api.service << SVC
[Unit]
Description=Haat Shop API
After=network-online.target
[Service]
WorkingDirectory=/opt/shop
Environment=ADMIN_PASSWORD=${ADMIN_PASSWORD}
Environment=SECRET_KEY=${SECRET_KEY}
Environment=DB_HOST=${DB_HOST}
Environment=DB_USER=${DB_USER}
Environment=DB_PASS=${DB_PASS}
Environment=DB_NAME=${DB_NAME}
ExecStart=/usr/bin/python3 -m gunicorn -w 2 -t 60 -b 127.0.0.1:5000 app:app
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
SVC

cat > /etc/httpd/conf.d/api.conf << 'CONF'
LimitRequestBody 6291456
ProxyTimeout 60
ProxyPass /api http://127.0.0.1:5000/api
ProxyPassReverse /api http://127.0.0.1:5000/api
CONF

httpd -t
systemctl daemon-reload
systemctl enable --now shop-api
systemctl enable httpd
systemctl restart httpd
echo "SETUP COMPLETE"
