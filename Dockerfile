FROM public.ecr.aws/lambda/python:3.9

RUN pip install --no-cache-dir scikit-learn==1.3.2 xgboost==2.0.3 pandas==2.1.4 boto3==1.34.0

COPY app.py /var/task/
WORKDIR /var/task

CMD ["app.lambda_handler"]