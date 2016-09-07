 var a= 0;
 var b = 0;
 var x= 0;



function result(){
  document.getElementById('result').innerHTML=x;
}

function add(a, b) {
  return a+b;
}

function substract(a, b) {
  return a-b;
}

function multiply(a, b) {
  return a*b;
}

function divide(a, b) {
  return a/b;
}

function ac(){
    a=2;
    b=2;
    document.getElementById('result').innerHTML = 0;
  }

function n1() {
  if (a === 0) {
    a=a+1;
    document.getElementById('result').innerHTML = 1;
  }
  else {
    b=b+1;
    document.getElementById('result').innerHTML = 1;
  }

}
