HAAT. DEMO STORE  (EC2 + ALB + Auto Scaling + RDS MySQL + S3)

1. S3: create a bucket, upload  site/  ->  s3://BUCKET/site/   and  images/  ->  s3://BUCKET/images/
2. RDS: MySQL instance. Its security group must allow port 3306 FROM the EC2 security group.
   (The app creates the database, tables and 6 starter products by itself.)
3. IAM: instance profile with S3 read access (s3:GetObject, s3:ListBucket) on the bucket.
4. Launch Template: Amazon Linux 2023, paste user-data.sh after editing the 7 values at the top.
5. Target group health check path: /health      Security group: ALB -> EC2 on port 80.
6. Open the ALB DNS name. Admin dashboard: /admin.html

Troubleshooting on an instance:
  sudo journalctl -u shop-api -n 50 --no-pager
  curl -i http://127.0.0.1:5000/api/health
  sudo tail -50 /var/log/shop-setup.log
