const http = require('http');

const options = {
  hostname: 'localhost',
  port: 8070,
  path: '/api/geo/stream?url=https%3A%2F%2Fexample.com&include_fix=true',
  method: 'GET',
  headers: {
    'Accept': 'text/event-stream'
  }
};

const req = http.request(options, (res) => {
  console.log(`Status: ${res.statusCode}`);
  console.log(`Headers: ${JSON.stringify(res.headers)}`);
  
  res.on('data', (chunk) => {
    console.log(`Data: ${chunk}`);
  });
  
  res.on('end', () => {
    console.log('End of response');
  });
});

req.on('error', (e) => {
  console.error(`Error: ${e.message}`);
});

req.end();